from __future__ import annotations

import json
import struct
import time
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from core.diagnostics.schemas import DeviceOutputEnvelope, OutputKind

# ── Metadata Constants ────────────────────────────────────────────────────────

CONTRACT_VERSION = "1.0.0"
SCHEMA_REVISION = "2026-09-17-v1"
SUPPORTED_AGENT_VERSIONS = ("1.7.6", "1.7.7")
PUBLISHED_AGENT_RELEASE = "1.7.7"

METHOD_STREAM_CONTROL = 7000
METHOD_EXEC_COMMAND = 7001
METHOD_CANCEL_TASK = 7002
SUPPORTED_METHODS = (METHOD_STREAM_CONTROL, METHOD_EXEC_COMMAND, METHOD_CANCEL_TASK)

SUPPORTED_7000_ACTIONS = frozenset([
    "inventory_get",
    "stream_start",
    "lease_renew",
    "stream_stop",
    "mouse_click",
    "key_event",
    "shortcut_action",
])

SUPPORTED_7001_SHELLS = frozenset(["cmd", "powershell"])

SUPPORTED_PRESENCE_EVENTS = frozenset([
    "app_online",
    "app_offline",
    "svc_online",
    "svc_offline",
])

FORBIDDEN_COMMERCIAL_FIELDS = frozenset([
    "billing",
    "price",
    "tariff",
    "cost",
    "payment",
    "fee",
    "amount",
    "currency",
    "invoice",
    "balance",
    "account",
    "subscription",
    "entitlement",
    "tenant_id",
    "org_id",
    "kopeck",
    "ruble",
    "rub",
    "subledger",
])


# ── Exceptions ────────────────────────────────────────────────────────────────


class AgentContractError(Exception):
    """Base exception for all agent contract violations."""


class CommercialFieldViolationError(AgentContractError):
    """Raised when commercial or billing data is detected in agent payloads."""


class UnknownCapabilityError(AgentContractError):
    """Raised when an unknown method, action, or shell is requested."""


class ContractValidationError(AgentContractError):
    """Raised when a payload fails JSON schema or contract invariant validation."""


# ── Pydantic Schemas Mirroring Agent Contract v1 ──────────────────────────────


class AgentStrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PresenceEventPayload(StrEnum):
    APP_ONLINE = "app_online"
    APP_OFFLINE = "app_offline"
    SVC_ONLINE = "svc_online"
    SVC_OFFLINE = "svc_offline"


class RPC7000Action(StrEnum):
    INVENTORY_GET = "inventory_get"
    STREAM_START = "stream_start"
    LEASE_RENEW = "lease_renew"
    STREAM_STOP = "stream_stop"
    MOUSE_CLICK = "mouse_click"
    KEY_EVENT = "key_event"
    SHORTCUT_ACTION = "shortcut_action"


class RPC7000StreamMode(StrEnum):
    DESKTOP = "desktop"
    CAMERA = "camera"


class RPC7000MouseButton(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"
    DOUBLE_LEFT = "double_left"


class RPC7000ClickType(StrEnum):
    CLICK = "click"
    DOWN = "down"
    UP = "up"
    DOUBLE = "double"


class RPC7000Shortcut(StrEnum):
    CTRL_ALT_DEL = "ctrl_alt_del"
    WIN_L = "win_l"
    ALT_TAB = "alt_tab"
    WIN_D = "win_d"
    ENTER = "enter"
    ESCAPE = "escape"


class RPC7000Status(StrEnum):
    OK = "ok"
    STARTED = "started"
    RENEWED = "renewed"
    STOPPED = "stopped"
    INJECTED = "injected"
    ERROR = "error"
    BUSY = "busy"
    UNSUPPORTED = "unsupported"


class RPC7000ErrorCode(StrEnum):
    DESKTOP_LOCKED = "desktop_locked"
    SESSION_UNAVAILABLE = "session_unavailable"
    ALREADY_RUNNING = "already_running"
    INVALID_BUTTON = "invalid_button"
    FORBIDDEN_KEY = "forbidden_key"
    UNSUPPORTED_ACTION = "unsupported_action"
    DEVICE_NOT_FOUND = "device_not_found"
    ENCODER_FAILURE = "encoder_failure"


class RPC7000Display(AgentStrictBaseModel):
    device_name: str
    display_index: int
    width: int | None = None
    height: int | None = None
    is_primary: bool | None = None


class RPC7000Camera(AgentStrictBaseModel):
    device_name: str
    camera_index: int


class RPC7000Request(AgentStrictBaseModel):
    method_code: Literal[7000] = 7000
    action: RPC7000Action
    command_id: str = Field(min_length=1)
    sn: str = Field(pattern=r"^[0-9A-Za-z_-]{6,32}$")
    stream_instance_id: str | None = None
    stream_mode: RPC7000StreamMode | None = None
    display_index: int | None = Field(default=None, ge=0)
    camera_index: int | None = Field(default=None, ge=0)
    fps: int | None = Field(default=None, ge=1, le=60)
    bitrate_kbps: int | None = Field(default=None, ge=100, le=20000)
    lease_sec: int | None = Field(default=None, ge=5, le=3600)
    input_enabled: bool | None = None
    x_norm: float | None = Field(default=None, ge=0.0, le=1.0)
    y_norm: float | None = Field(default=None, ge=0.0, le=1.0)
    button: RPC7000MouseButton | None = None
    click_type: RPC7000ClickType | None = None
    vk: int | None = Field(default=None, ge=1, le=255)
    scan_code: int | None = Field(default=None, ge=0)
    is_down: bool | None = None
    is_extended: bool | None = None
    shortcut: RPC7000Shortcut | None = None


class RPC7000Response(AgentStrictBaseModel):
    status: RPC7000Status
    command_id: str
    error: str | None = None
    displays: list[RPC7000Display] | None = None
    cameras: list[RPC7000Camera] | None = None
    active_stream: dict[str, Any] | None = None
    stream_instance_id: str | None = None
    stream_mode: RPC7000StreamMode | None = None
    display_index: int | None = None
    camera_index: int | None = None
    fps: int | None = None
    bitrate_kbps: int | None = None
    lease_sec: int | None = None
    expires_at_ms: int | None = None
    rtp_port: int | None = None
    rtcp_port: int | None = None
    input_enabled: bool | None = None
    desktop_locked: bool | None = None
    session_available: bool | None = None


class RPC7001Shell(StrEnum):
    CMD = "cmd"
    POWERSHELL = "powershell"


class RPC7001Status(StrEnum):
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RPC7001Request(AgentStrictBaseModel):
    id: str = Field(min_length=1)
    method_code: Literal[7001] = 7001
    session_id: str = Field(min_length=1)
    command_line: str = Field(min_length=1)
    shell: RPC7001Shell
    ttl_sec: int | None = Field(default=None, ge=1, le=3600)
    topic: str | None = None


class RPC7001StreamChunk(AgentStrictBaseModel):
    session_id: str = Field(min_length=1)
    seq: int = Field(ge=1)
    data: str
    stream: Literal["stdout", "stderr"] | None = None
    eof: bool = False
    exit_code: int | None = None


class RPC7001Response(AgentStrictBaseModel):
    id: str
    session_id: str
    method_code: Literal[7001] = 7001
    status: RPC7001Status
    exit_code: int
    execution_time_ms: int | None = Field(default=None, ge=0)
    error: str | None = None


class RPC7002Status(StrEnum):
    CANCELLED = "cancelled"
    NOT_FOUND = "not_found"
    ALREADY_FINISHED = "already_finished"


class RPC7002Request(AgentStrictBaseModel):
    id: str = Field(min_length=1)
    method_code: Literal[7002] = 7002
    target_task_id: str = Field(min_length=1)
    target_session_id: str | None = None


class RPC7002Response(AgentStrictBaseModel):
    id: str
    method_code: Literal[7002] = 7002
    target_task_id: str
    status: RPC7002Status
    message: str | None = None


# ── Deduplicators ─────────────────────────────────────────────────────────────


class ChunkDeduplicator:
    """Tracks sequence numbers per (sn, session_id) to discard duplicate chunks."""

    def __init__(self, max_entries: int = 10_000) -> None:
        self._seen: dict[tuple[str, str], set[int]] = {}
        self._max_entries = max_entries

    def is_duplicate(self, sn: str, session_id: str, seq: int) -> bool:
        key = (sn, session_id)
        return seq in self._seen.get(key, ())

    def record(self, sn: str, session_id: str, seq: int) -> None:
        key = (sn, session_id)
        if key not in self._seen:
            if len(self._seen) >= self._max_entries:
                # Evict oldest entry
                oldest_key = next(iter(self._seen))
                del self._seen[oldest_key]
            self._seen[key] = set()
        self._seen[key].add(seq)

    def clear_session(self, sn: str, session_id: str) -> None:
        self._seen.pop((sn, session_id), None)


class CommandDeduplicator:
    """Tracks command IDs per sn to detect duplicate / retry responses."""

    def __init__(self, ttl_sec: float = 300.0) -> None:
        self._seen: dict[tuple[str, str], float] = {}
        self._ttl_sec = ttl_sec

    def is_duplicate(self, sn: str, command_id: str) -> bool:
        now = time.monotonic()
        self._cleanup(now)
        return (sn, command_id) in self._seen

    def record(self, sn: str, command_id: str) -> None:
        self._seen[(sn, command_id)] = time.monotonic()

    def _cleanup(self, now: float) -> None:
        if len(self._seen) > 2000:
            cutoff = now - self._ttl_sec
            keys_to_del = [k for k, ts in self._seen.items() if ts < cutoff]
            for k in keys_to_del:
                del self._seen[k]


# ── Commercial Guard ──────────────────────────────────────────────────────────


def assert_no_commercial_fields(data: Any, path: str = "payload") -> None:
    """Recursively validates that no financial or organizational fields leak to agent."""
    if isinstance(data, dict):
        for k, v in data.items():
            lower_k = str(k).lower()
            for forbidden in FORBIDDEN_COMMERCIAL_FIELDS:
                if forbidden in lower_k:
                    raise CommercialFieldViolationError(
                        f"Forbidden commercial field '{k}' detected at {path}. "
                        f"Agent Compatibility Contract v1 strictly prohibits financial fields."
                    )
            assert_no_commercial_fields(v, f"{path}.{k}")
    elif isinstance(data, (list, tuple)):
        for i, item in enumerate(data):
            assert_no_commercial_fields(item, f"{path}[{i}]")


# ── L4RTP Wire Protocol Verifier ──────────────────────────────────────────────


def verify_l4rtp_preamble(wire_bytes: bytes) -> dict[str, Any]:
    """Validates and parses L4RTP preamble packet per l4rtp_wire_protocol.schema.json."""
    if len(wire_bytes) < 8:
        raise ContractValidationError(
            f"L4RTP preamble wire bytes length {len(wire_bytes)} < minimum 8 bytes"
        )
    magic = wire_bytes[:4].decode("ascii", errors="replace")
    if magic != "L4RT":
        raise ContractValidationError(f"Invalid L4RTP magic: expected 'L4RT', got {magic!r}")
    version = wire_bytes[4]
    if version != 1:
        raise ContractValidationError(f"Invalid L4RTP version: expected 1, got {version}")
    reserved = wire_bytes[5]
    if reserved != 0:
        raise ContractValidationError(f"Invalid L4RTP reserved field: expected 0, got {reserved}")
    sn_len = struct.unpack(">H", wire_bytes[6:8])[0]
    total_expected = 8 + sn_len
    if len(wire_bytes) < total_expected:
        raise ContractValidationError(
            f"L4RTP preamble truncated: expected {total_expected} bytes, got {len(wire_bytes)}"
        )
    sn = wire_bytes[8:total_expected].decode("ascii", errors="replace")
    return {
        "magic": magic,
        "version": version,
        "reserved": reserved,
        "sn_len": sn_len,
        "sn": sn,
    }


def verify_l4rtp_frame_header(header_bytes: bytes) -> dict[str, Any]:
    """Validates 4-byte (8 hex characters) L4RTP multiplexed stream frame header."""
    if len(header_bytes) < 4:
        raise ContractValidationError(
            f"L4RTP frame header length {len(header_bytes)} < required 4 bytes"
        )
    channel = header_bytes[0]
    if channel not in (1, 2):
        raise ContractValidationError(f"Invalid L4RTP channel: expected 1 or 2, got {channel}")
    reserved = header_bytes[1]
    payload_len = struct.unpack(">H", header_bytes[2:4])[0]
    channel_name = "RTP" if channel == 1 else "RTCP"
    return {
        "channel": channel,
        "channel_name": channel_name,
        "reserved": reserved,
        "payload_length_bytes": payload_len,
        "header_hex": header_bytes[:4].hex(),
    }


# ── Main Provider Adapter ─────────────────────────────────────────────────────


class AgentContractV1Adapter:
    """Provider compatibility adapter implementing Agent Contract v1 specifications."""

    def __init__(self) -> None:
        self.chunk_dedup = ChunkDeduplicator()
        self.cmd_dedup = CommandDeduplicator()

    # ── Outbound Task & Command Adaptation ────────────────────────────────────

    def adapt_outbound_stream_control(
        self,
        cmd: Any,
        sn: str,
    ) -> dict[str, Any]:
        """Translates internal server commands to strictly conforming RPC 7000 request."""
        if hasattr(cmd, "model_dump"):
            raw = cmd.model_dump(mode="json")
        elif isinstance(cmd, dict):
            raw = dict(cmd)
        else:
            raw = dict(cmd.__dict__)

        # Ensure no commercial fields leak
        assert_no_commercial_fields(raw)

        action = raw.get("action") or raw.get("type")
        if not action or action not in SUPPORTED_7000_ACTIONS:
            raise UnknownCapabilityError(f"Unsupported action for method 7000: {action}")

        command_id = str(raw.get("command_id") or raw.get("cmd_id") or "")
        if not command_id:
            raise ContractValidationError("Missing required command_id for method 7000 request")

        payload: dict[str, Any] = {
            "method_code": METHOD_STREAM_CONTROL,
            "action": action,
            "command_id": command_id,
            "sn": sn,
        }

        # Optional field mapping & coordinate conversion
        if "stream_instance_id" in raw and raw["stream_instance_id"]:
            payload["stream_instance_id"] = str(raw["stream_instance_id"])

        if "mode" in raw and raw["mode"]:
            mode_val = "desktop" if raw["mode"] in ("desktop", "screen") else "camera"
            payload["stream_mode"] = mode_val
        elif "stream_mode" in raw and raw["stream_mode"]:
            payload["stream_mode"] = raw["stream_mode"]

        if "display_index" in raw and raw["display_index"] is not None:
            payload["display_index"] = int(raw["display_index"])
        elif "source_id" in raw and raw["source_id"] is not None:
            try:
                payload["display_index"] = int(raw["source_id"])
            except (ValueError, TypeError):
                payload["display_index"] = 0

        if "camera_index" in raw and raw["camera_index"] is not None:
            payload["camera_index"] = int(raw["camera_index"])

        if "fps" in raw and raw["fps"] is not None:
            payload["fps"] = int(raw["fps"])
        if "bitrate_kbps" in raw and raw["bitrate_kbps"] is not None:
            payload["bitrate_kbps"] = int(raw["bitrate_kbps"])
        if "lease_sec" in raw and raw["lease_sec"] is not None:
            payload["lease_sec"] = int(raw["lease_sec"])
        elif "ttl_sec" in raw and raw["ttl_sec"] is not None:
            payload["lease_sec"] = int(raw["ttl_sec"])

        if "input_enabled" in raw and raw["input_enabled"] is not None:
            payload["input_enabled"] = bool(raw["input_enabled"])

        # Coordinates: Convert integer 0..65535 to normalized 0.0..1.0 float if needed
        if "x_norm" in raw and raw["x_norm"] is not None:
            payload["x_norm"] = float(raw["x_norm"])
        elif "x" in raw and raw["x"] is not None:
            payload["x_norm"] = round(float(raw["x"]) / 65535.0, 4)

        if "y_norm" in raw and raw["y_norm"] is not None:
            payload["y_norm"] = float(raw["y_norm"])
        elif "y" in raw and raw["y"] is not None:
            payload["y_norm"] = round(float(raw["y"]) / 65535.0, 4)

        if "button" in raw and raw["button"]:
            payload["button"] = str(raw["button"])
        if "click_type" in raw and raw["click_type"]:
            payload["click_type"] = str(raw["click_type"])
        if "vk" in raw and raw["vk"] is not None:
            payload["vk"] = int(raw["vk"])
        if "scan_code" in raw and raw["scan_code"] is not None:
            payload["scan_code"] = int(raw["scan_code"])
        if "is_down" in raw and raw["is_down"] is not None:
            payload["is_down"] = bool(raw["is_down"])
        elif "kind" in raw and raw["kind"] in ("down", "up"):
            payload["is_down"] = raw["kind"] == "down"
        if "is_extended" in raw and raw["is_extended"] is not None:
            payload["is_extended"] = bool(raw["is_extended"])
        if "shortcut" in raw and raw["shortcut"]:
            payload["shortcut"] = str(raw["shortcut"])
        elif "action" in raw and raw["action"] in RPC7000Shortcut.__members__.values():
            payload["shortcut"] = str(raw["action"])

        # Strictly validate against RPC7000Request schema (forbids internal & commercial fields)
        try:
            validated = RPC7000Request.model_validate(payload)
            return validated.model_dump(mode="json", exclude_none=True)
        except ValidationError as e:
            raise ContractValidationError(f"Invalid outbound RPC 7000 request: {e}") from e

    def adapt_outbound_exec(
        self,
        *,
        task_id: str,
        session_id: str | UUID,
        command_line: str,
        shell: str = "cmd",
        ttl_sec: int = 30,
        sn: str,
        topic: str | None = None,
    ) -> dict[str, Any]:
        """Translates execution command to strictly conforming RPC 7001 request."""
        if shell not in SUPPORTED_7001_SHELLS:
            raise UnknownCapabilityError(f"Unsupported shell for method 7001: {shell}")

        req_dict = {
            "id": str(task_id),
            "method_code": METHOD_EXEC_COMMAND,
            "session_id": str(session_id),
            "command_line": str(command_line),
            "shell": shell,
            "ttl_sec": int(ttl_sec),
            "topic": topic or f"dev/{sn}/out",
        }
        assert_no_commercial_fields(req_dict)
        try:
            validated = RPC7001Request.model_validate(req_dict)
            return validated.model_dump(mode="json", exclude_none=True)
        except ValidationError as e:
            raise ContractValidationError(f"Invalid outbound RPC 7001 request: {e}") from e

    def adapt_outbound_cancel(
        self,
        *,
        task_id: str,
        target_task_id: str,
        target_session_id: str | None = None,
    ) -> dict[str, Any]:
        """Translates cancellation request to strictly conforming RPC 7002 request."""
        req_dict: dict[str, Any] = {
            "id": str(task_id),
            "method_code": METHOD_CANCEL_TASK,
            "target_task_id": str(target_task_id),
        }
        if target_session_id is not None:
            req_dict["target_session_id"] = str(target_session_id)

        assert_no_commercial_fields(req_dict)
        try:
            validated = RPC7002Request.model_validate(req_dict)
            return validated.model_dump(mode="json", exclude_none=True)
        except ValidationError as e:
            raise ContractValidationError(f"Invalid outbound RPC 7002 request: {e}") from e

    # ── Inbound Device Response & Stream Chunk Adaptation ─────────────────────

    def adapt_inbound_stream_chunk(
        self,
        payload: dict[str, Any] | str | bytes,
        sn: str,
    ) -> tuple[DeviceOutputEnvelope, bool]:
        """Validates incoming streaming chunk on dev/{SN}/out and maps to DeviceOutputEnvelope.

        Returns (envelope, is_duplicate).
        """
        if isinstance(payload, bytes):
            payload = json.loads(payload.decode("utf-8"))
        elif isinstance(payload, str):
            payload = json.loads(payload)

        try:
            chunk = RPC7001StreamChunk.model_validate(payload)
        except ValidationError as e:
            raise ContractValidationError(f"Invalid dev/{sn}/out stream chunk: {e}") from e

        # Duplicate check
        is_dup = self.chunk_dedup.is_duplicate(sn, chunk.session_id, chunk.seq)
        if not is_dup:
            self.chunk_dedup.record(sn, chunk.session_id, chunk.seq)

        # Map to DeviceOutputEnvelope
        if chunk.eof:
            kind = OutputKind.RESULT
        elif chunk.stream == "stderr":
            kind = OutputKind.STDERR
        else:
            kind = OutputKind.STDOUT

        envelope = DeviceOutputEnvelope(
            v=1,
            session_id=chunk.session_id,
            seq=chunk.seq,
            kind=kind,
            stream=chunk.stream or "stdout",
            data=chunk.data,
            eof=chunk.eof,
            exit_code=chunk.exit_code,
        )
        return envelope, is_dup

    def adapt_inbound_stream_control_response(
        self,
        payload: dict[str, Any] | str | bytes,
        sn: str,
    ) -> tuple[RPC7000Response, bool]:
        """Validates incoming 7000 response on dev/{SN}/res.

        Returns (response, is_duplicate).
        """
        if isinstance(payload, bytes):
            payload = json.loads(payload.decode("utf-8"))
        elif isinstance(payload, str):
            payload = json.loads(payload)

        try:
            resp = RPC7000Response.model_validate(payload)
        except ValidationError as e:
            raise ContractValidationError(f"Invalid dev/{sn}/res 7000 response: {e}") from e

        is_dup = self.cmd_dedup.is_duplicate(sn, resp.command_id)
        if not is_dup:
            self.cmd_dedup.record(sn, resp.command_id)

        return resp, is_dup

    def adapt_inbound_exec_response(
        self,
        payload: dict[str, Any] | str | bytes,
        sn: str,
    ) -> tuple[RPC7001Response, bool]:
        """Validates incoming 7001 execution completion response on dev/{SN}/res."""
        if isinstance(payload, bytes):
            payload = json.loads(payload.decode("utf-8"))
        elif isinstance(payload, str):
            payload = json.loads(payload)

        try:
            resp = RPC7001Response.model_validate(payload)
        except ValidationError as e:
            raise ContractValidationError(f"Invalid dev/{sn}/res 7001 response: {e}") from e

        is_dup = self.cmd_dedup.is_duplicate(sn, resp.id)
        if not is_dup:
            self.cmd_dedup.record(sn, resp.id)

        return resp, is_dup

    def adapt_inbound_cancel_response(
        self,
        payload: dict[str, Any] | str | bytes,
        sn: str,
    ) -> tuple[RPC7002Response, bool]:
        """Validates incoming 7002 task cancel response on dev/{SN}/res."""
        if isinstance(payload, bytes):
            payload = json.loads(payload.decode("utf-8"))
        elif isinstance(payload, str):
            payload = json.loads(payload)

        try:
            resp = RPC7002Response.model_validate(payload)
        except ValidationError as e:
            raise ContractValidationError(f"Invalid dev/{sn}/res 7002 response: {e}") from e

        is_dup = self.cmd_dedup.is_duplicate(sn, resp.id)
        if not is_dup:
            self.cmd_dedup.record(sn, resp.id)

        return resp, is_dup

    # ── Presence Validation ───────────────────────────────────────────────────

    def validate_presence_message(
        self,
        *,
        topic: str,
        payload: str | bytes,
        qos: int = 1,
        retain: bool = True,
    ) -> tuple[str, str, bool]:
        """Validates MQTT presence topic, QoS 1, retain=True, and payload.

        Returns (client_type, payload_str, is_online).
        """
        if qos != 1:
            raise ContractValidationError(
                f"Agent presence message requires QoS 1 per contract, got QoS {qos}"
            )
        if not retain:
            raise ContractValidationError(
                f"Agent presence message requires retain=true per contract, got retain={retain}"
            )

        norm_topic = topic.replace(".", "/")
        parts = norm_topic.split("/")
        if len(parts) != 3 or parts[0] != "dev" or parts[2] not in ("app", "svc"):
            raise ContractValidationError(f"Invalid presence topic pattern: {topic}")

        channel = parts[2]  # "app" or "svc"
        body = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
        body = body.strip().strip('"').lower()

        if body not in SUPPORTED_PRESENCE_EVENTS:
            raise ContractValidationError(
                f"Unknown presence payload {body!r}; expected one of {list(SUPPORTED_PRESENCE_EVENTS)}"
            )

        if channel == "app" and body not in ("app_online", "app_offline"):
            raise ContractValidationError(
                f"Payload {body} mismatch for channel dev/{{SN}}/app"
            )
        if channel == "svc" and body not in ("svc_online", "svc_offline"):
            raise ContractValidationError(
                f"Payload {body} mismatch for channel dev/{{SN}}/svc"
            )

        is_online = body in ("app_online", "svc_online")
        client_type = "main_app" if channel == "app" else "extra_service"
        return client_type, body, is_online


agent_contract_v1_adapter = AgentContractV1Adapter()
