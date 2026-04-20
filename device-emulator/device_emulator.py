"""
Device emulator for the IoT RPC/REST stack.

Implements:
  * Mock handler for RPC method_code = 51 (open cell) — emulates the real
    3-phase flow described in ``docs/ai-agent-integration-guide.md``:
      1. Immediately replies with a ``res`` (``status_code=200``) — this only
         confirms that the command was successfully received by the device,
         **not** that the cell has been opened physically.
      2. After ``CELL_OPEN_DELAY`` seconds (emulating the physical action),
         publishes ``event_type_code = 13`` (``CellOpenEvent``) carrying the
         cell number in tag ``304``.
      3. ``CELL_CLOSE_DELAY`` seconds after event 13, publishes
         ``event_type_code = 14`` (cell closed) with the same format and the
         same cell number — emulating the physical closing of the cell.
  * Periodic healthcheck event (event_type_code = 44), once per minute.
  * Periodic test event (event_type_code = 90), once per minute.

Certificates are taken from filesystem paths supplied via environment variables
(MQTT_CA_FILE / MQTT_CERT_FILE / MQTT_KEY_FILE).  The files may appear on the
host *after* the container starts — at startup the emulator polls the paths
until all three files are present and parse correctly as PEM.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import ssl
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import paho.mqtt.client as mqtt
from OpenSSL import crypto
from paho.mqtt.packettypes import PacketTypes


# --------------------------------------------------------------------------- #
# Configuration (env vars)
# --------------------------------------------------------------------------- #
MQTT_HOST = os.environ.get("MQTT_HOST", "dev.leo4.ru")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "8883"))

MQTT_CA_FILE = os.environ.get("MQTT_CA_FILE", "/certs/ca.crt")
MQTT_CERT_FILE = os.environ.get("MQTT_CERT_FILE", "/certs/cert.pem")
MQTT_KEY_FILE = os.environ.get("MQTT_KEY_FILE", "/certs/key.pem")

CERT_WAIT_INTERVAL = float(os.environ.get("CERT_WAIT_INTERVAL", "5"))
CERT_WAIT_TIMEOUT = float(os.environ.get("CERT_WAIT_TIMEOUT", "0"))  # 0 = forever

HEALTHCHECK_INTERVAL = float(os.environ.get("HEALTHCHECK_INTERVAL", "60"))
TEST_EVENT_INTERVAL = float(os.environ.get("TEST_EVENT_INTERVAL", "60"))

CELL_OPEN_DELAY_SECONDS = float(os.environ.get("CELL_OPEN_DELAY", "1.0"))
CELL_CLOSE_DELAY_SECONDS = float(os.environ.get("CELL_CLOSE_DELAY", "30.0"))

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("device-emulator")

# Method handled by this mock implementation
METHOD_OPEN_CELL = 51

# Event codes
EVENT_HEALTHCHECK = 44
EVENT_TEST = 90
EVENT_CELL_OPEN = 13
EVENT_CELL_CLOSE = 14


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _file_is_valid_pem(path: str, kind: str) -> bool:
    """Return True if `path` exists and contains a parseable PEM object.

    `kind` is one of: "cert", "key", "ca".
    """
    try:
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            return False
        with open(path, "rb") as fh:
            data = fh.read()
        if kind in ("cert", "ca"):
            crypto.load_certificate(crypto.FILETYPE_PEM, data)
        elif kind == "key":
            crypto.load_privatekey(crypto.FILETYPE_PEM, data)
        return True
    except Exception as exc:  # noqa: BLE001 — we want to log any parse failure
        log.debug("PEM check failed for %s (%s): %s", path, kind, exc)
        return False


def wait_for_certificates(stop_event: threading.Event) -> None:
    """Block until CA, cert and key files exist on the host *and* parse.

    Honors `CERT_WAIT_TIMEOUT` (0 = wait forever) and the supplied stop_event.
    """
    deadline: Optional[float] = None
    if CERT_WAIT_TIMEOUT > 0:
        deadline = time.monotonic() + CERT_WAIT_TIMEOUT

    log.info(
        "Waiting for certificate files: CA=%s cert=%s key=%s",
        MQTT_CA_FILE,
        MQTT_CERT_FILE,
        MQTT_KEY_FILE,
    )

    while not stop_event.is_set():
        ca_ok = _file_is_valid_pem(MQTT_CA_FILE, "ca")
        cert_ok = _file_is_valid_pem(MQTT_CERT_FILE, "cert")
        key_ok = _file_is_valid_pem(MQTT_KEY_FILE, "key")

        if ca_ok and cert_ok and key_ok:
            log.info("Certificate files are available and valid.")
            return

        log.info(
            "Certificates not ready yet (ca=%s cert=%s key=%s) — retry in %.1fs",
            ca_ok, cert_ok, key_ok, CERT_WAIT_INTERVAL,
        )
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError(
                f"Certificate files were not ready within {CERT_WAIT_TIMEOUT}s"
            )
        stop_event.wait(CERT_WAIT_INTERVAL)


def extract_cn(cert_path: str) -> str:
    """Extract the CN (used as the device serial number) from the client cert."""
    with open(cert_path, "rb") as fh:
        x509 = crypto.load_certificate(crypto.FILETYPE_PEM, fh.read())
    components = {
        name.decode(): value.decode("utf-8")
        for name, value in x509.get_subject().get_components()
    }
    cn = components.get("CN")
    if not cn:
        raise RuntimeError(f"Certificate {cert_path} has no CN in subject")
    return cn


def _correlation_data(msg: mqtt.MQTTMessage) -> Optional[bytes]:
    props = getattr(msg, "properties", None)
    if props is None:
        return None
    return getattr(props, "CorrelationData", None)


def _user_properties(msg: mqtt.MQTTMessage) -> dict:
    props = getattr(msg, "properties", None)
    if props is None:
        return {}
    raw = getattr(props, "UserProperty", None) or []
    return dict(raw)


# --------------------------------------------------------------------------- #
# Device emulator
# --------------------------------------------------------------------------- #
class DeviceEmulator:
    def __init__(self, sn: str) -> None:
        self.sn = sn
        self.stop_event = threading.Event()

        self.topic_req = f"dev/{sn}/req"
        self.topic_res = f"dev/{sn}/res"
        self.topic_evt = f"dev/{sn}/evt"
        self.topic_ack = f"dev/{sn}/ack"

        self.topic_tsk = f"srv/{sn}/tsk"
        self.topic_rsp = f"srv/{sn}/rsp"
        self.topic_cmt = f"srv/{sn}/cmt"
        self.topic_eva = f"srv/{sn}/eva"

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            protocol=mqtt.MQTTv5,
            client_id=sn,
        )
        self.client.tls_set(
            ca_certs=MQTT_CA_FILE,
            certfile=MQTT_CERT_FILE,
            keyfile=MQTT_KEY_FILE,
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLSv1_2,
        )
        self.client.tls_insecure_set(False)

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        self._healthcheck_thread: Optional[threading.Thread] = None
        self._test_event_thread: Optional[threading.Thread] = None
        self._event_counter = 0
        self._event_counter_lock = threading.Lock()

    # ------------------------------------------------------------------ MQTT
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0 or getattr(reason_code, "is_failure", False) is False:
            log.info("Connected to MQTT broker %s:%s as %s", MQTT_HOST, MQTT_PORT, self.sn)
        else:
            log.error("Failed to connect: %s", reason_code)
            return

        client.subscribe(
            [
                (self.topic_tsk, 0),
                (self.topic_rsp, 1),
                (self.topic_cmt, 0),
                (self.topic_eva, 0),
            ]
        )

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code,
                       properties=None):
        log.warning("Disconnected from MQTT broker: %s", reason_code)

    def _on_message(self, client, userdata, msg):
        try:
            user_props = _user_properties(msg)
            corr = _correlation_data(msg)
            log.info(
                "RX %s | corr=%s | props=%s | payload=%r",
                msg.topic,
                corr,
                user_props,
                msg.payload,
            )

            if msg.topic == self.topic_tsk:
                self._handle_tsk(corr, user_props)
            elif msg.topic == self.topic_rsp:
                self._handle_rsp(corr, user_props, msg.payload)
            elif msg.topic == self.topic_cmt:
                log.info("CMT received for corr=%s, result_id=%s", corr, user_props.get("result_id"))
            elif msg.topic == self.topic_eva:
                log.debug("EVA received: %s", user_props)
        except Exception:
            log.exception("Failed to process message from %s", msg.topic)

    # ----------------------------------------------------------- RPC handling
    def _handle_tsk(self, corr: Optional[bytes], user_props: dict) -> None:
        """Server announced a task — request its parameters."""
        if corr is None:
            log.warning("TSK without CorrelationData — ignoring")
            return

        method_code = user_props.get("method_code")
        log.info("TSK announce: method_code=%s corr=%s", method_code, corr)

        # Optional ACK
        ack_props = mqtt.Properties(PacketTypes.PUBLISH)
        ack_props.CorrelationData = corr
        self.client.publish(self.topic_ack, b"", qos=0, properties=ack_props)

        # Request parameters of this specific task using the same correlation
        req_props = mqtt.Properties(PacketTypes.PUBLISH)
        req_props.CorrelationData = corr
        self.client.publish(self.topic_req, b"", qos=0, properties=req_props)
        log.info("REQ sent for corr=%s", corr)

    def _handle_rsp(self, corr: Optional[bytes], user_props: dict,
                    payload: bytes) -> None:
        """Server delivered task parameters — execute mock and reply with res."""
        if corr is None:
            log.warning("RSP without CorrelationData — ignoring")
            return

        method_code_raw = user_props.get("method_code")
        try:
            method_code = int(method_code_raw) if method_code_raw is not None else None
        except (TypeError, ValueError):
            method_code = None

        if method_code != METHOD_OPEN_CELL:
            log.warning(
                "Received unsupported method_code=%s — replying with status 501",
                method_code_raw,
            )
            self._publish_res(
                corr,
                {"result": "error",
                 "description": f"method_code {method_code_raw} not implemented"},
                status_code="501",
            )
            return

        rsp_payload = self._parse_json_payload(payload)
        cell_number = self._parse_cell_number(rsp_payload)
        log.info(
            "Method 51 (open cell) requested, cell=%s — acknowledging command "
            "immediately; physical open in %.1fs, close %.1fs after that",
            cell_number,
            CELL_OPEN_DELAY_SECONDS,
            CELL_CLOSE_DELAY_SECONDS,
        )

        # Phase 1: immediately confirm that the command was *received* by the
        # device.  Per the 3-phase flow described in the AI-agent integration
        # guide, this `res` only signals successful receipt of the command —
        # the physical open/close are reported afterwards via events 13/14.
        ack_result = {
            "result": "ok",
            "method_code": METHOD_OPEN_CELL,
            "cl": cell_number,
            "accepted": True,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self._publish_res(corr, ack_result, status_code="200")
        log.info("Cell %s command accepted (mock); RES sent", cell_number)

        # Phases 2 & 3 happen asynchronously so we don't block the MQTT
        # callback thread and so that we can handle further commands in the
        # meantime.
        thread = threading.Thread(
            target=self._emulate_physical_cell_cycle,
            args=(cell_number,),
            name=f"cell-cycle-{cell_number}",
            daemon=True,
        )
        thread.start()

    def _emulate_physical_cell_cycle(self, cell_number: Optional[int]) -> None:
        """Emulate the physical open (event 13) and close (event 14) phases."""
        # Phase 2: wait for the physical "open", then publish event 13.
        if self.stop_event.wait(CELL_OPEN_DELAY_SECONDS):
            log.info(
                "Shutdown requested before cell %s physical open — aborting cycle",
                cell_number,
            )
            return
        try:
            self._publish_event(
                EVENT_CELL_OPEN,
                self._cell_event_payload(cell_number),
            )
        except Exception:
            log.exception("Failed to publish CellOpenEvent (13) for cell %s",
                          cell_number)

        # Phase 3: wait CELL_CLOSE_DELAY_SECONDS and publish event 14.
        if self.stop_event.wait(CELL_CLOSE_DELAY_SECONDS):
            log.info(
                "Shutdown requested before cell %s physical close — skipping event 14",
                cell_number,
            )
            return
        try:
            self._publish_event(
                EVENT_CELL_CLOSE,
                self._cell_event_payload(cell_number),
            )
        except Exception:
            log.exception("Failed to publish CellCloseEvent (14) for cell %s",
                          cell_number)

    @staticmethod
    def _cell_event_payload(cell_number: Optional[int]) -> dict:
        """Build the strict protocol payload for cell open/close events."""
        return {"300": [{"304": int(cell_number) if cell_number is not None else 0}]}

    @staticmethod
    def _parse_json_payload(payload: bytes) -> dict[str, Any]:
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    @staticmethod
    def _parse_cell_number(data: dict[str, Any]) -> Optional[int]:
        items = data.get("dt")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict) or "cl" not in item:
                    continue
                try:
                    return int(item["cl"])
                except (TypeError, ValueError):
                    continue
        # Fallback — top-level "cl"
        if "cl" in data:
            try:
                return int(data["cl"])
            except (TypeError, ValueError):
                return None
        nested_payload = data.get("payload")
        if isinstance(nested_payload, dict):
            return DeviceEmulator._parse_cell_number(nested_payload)
        return None

    @staticmethod
    def _format_timestamp(value: datetime) -> str:
        rounded = value + timedelta(microseconds=5_000)
        base = rounded.isoformat(timespec="seconds")
        centiseconds = rounded.microsecond // 10_000
        if centiseconds == 0:
            return base
        return f"{base[:-6]}.{centiseconds:02d}{base[-6:]}"

    @staticmethod
    def _build_event_message(
        event_type_code: int,
        dev_event_id: int,
        payload: dict,
        now: Optional[datetime] = None,
    ) -> dict:
        full_payload = {"101": dev_event_id}
        for key, value in payload.items():
            if key not in {"101", "102", "200"}:
                full_payload[key] = value
        full_payload["102"] = DeviceEmulator._format_timestamp(
            now or datetime.now(timezone.utc)
        )
        full_payload["200"] = event_type_code
        return full_payload

    def _publish_res(
        self,
        corr: bytes,
        result: dict,
        status_code: str,
        ext_id: str = "0",
    ) -> None:
        props = mqtt.Properties(PacketTypes.PUBLISH)
        props.CorrelationData = corr
        props.UserProperty = [
            ("status_code", status_code),
            ("ext_id", ext_id),
        ]
        self.client.publish(
            self.topic_res,
            json.dumps(result),
            qos=0,
            properties=props,
        )

    # ----------------------------------------------------------------- Events
    def _next_event_id(self) -> int:
        with self._event_counter_lock:
            self._event_counter += 1
            return 10000 + self._event_counter

    def _publish_event(self, event_type_code: int, payload: dict) -> None:
        dev_event_id = self._next_event_id()
        props = mqtt.Properties(PacketTypes.PUBLISH)
        props.CorrelationData = uuid.uuid4().bytes
        props.UserProperty = [
            ("event_type_code", str(event_type_code)),
            ("dev_event_id", str(dev_event_id)),
            ("dev_timestamp", str(int(time.time()))),
        ]
        full_payload = self._build_event_message(event_type_code, dev_event_id, payload)

        self.client.publish(
            self.topic_evt,
            json.dumps(full_payload),
            qos=0,
            properties=props,
        )
        log.info(
            "EVT sent: type=%s dev_event_id=%s payload=%s",
            event_type_code, dev_event_id, full_payload,
        )

    def _periodic(self, interval: float, event_type_code: int,
                  payload_factory) -> None:
        # Slight initial delay so we publish *after* the connection is up
        if self.stop_event.wait(2.0):
            return
        while not self.stop_event.is_set():
            try:
                self._publish_event(event_type_code, payload_factory())
            except Exception:
                log.exception("Failed to publish event %s", event_type_code)
            if self.stop_event.wait(interval):
                return

    # ------------------------------------------------------------- Lifecycle
    def start(self) -> None:
        log.info("Connecting to %s:%s ...", MQTT_HOST, MQTT_PORT)
        self.client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        self.client.loop_start()

        self._healthcheck_thread = threading.Thread(
            target=self._periodic,
            args=(HEALTHCHECK_INTERVAL, EVENT_HEALTHCHECK,
                  lambda: {"description": "healthcheck",
                           "300": [{"310": "device-emulator", "324": self.sn}]}),
            name="healthcheck",
            daemon=True,
        )
        self._test_event_thread = threading.Thread(
            target=self._periodic,
            args=(TEST_EVENT_INTERVAL, EVENT_TEST,
                  lambda: {"description": "test event",
                           "300": [{"310": "device-emulator", "324": self.sn}]}),
            name="test-event",
            daemon=True,
        )
        self._healthcheck_thread.start()
        self._test_event_thread.start()

    def stop(self) -> None:
        log.info("Stopping device emulator ...")
        self.stop_event.set()
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            log.exception("Error while disconnecting MQTT client")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main() -> int:
    stop_event = threading.Event()

    def _sig(_signum, _frame):
        log.info("Signal received — shutting down")
        stop_event.set()

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    try:
        wait_for_certificates(stop_event)
    except TimeoutError as exc:
        log.error("%s", exc)
        return 2

    if stop_event.is_set():
        return 0

    try:
        sn = extract_cn(MQTT_CERT_FILE)
    except Exception as exc:  # noqa: BLE001
        log.error("Cannot extract CN from %s: %s", MQTT_CERT_FILE, exc)
        return 2

    log.info("Device SN (CN): %s", sn)

    emulator = DeviceEmulator(sn)
    emulator.stop_event = stop_event  # share the same flag
    try:
        emulator.start()
    except Exception:
        log.exception("Failed to start emulator")
        return 1

    try:
        while not stop_event.is_set():
            stop_event.wait(1.0)
    finally:
        emulator.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
