from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from core.diagnostics.schemas import DeviceOutputEnvelope
from core.diagnostics.sessions import DiagnosticsSessionRegistry, registry
from core.logging_config import setup_module_logger

log = setup_module_logger(__name__, "diagnostics_mqtt_bridge.log")


def extract_sn_from_output_routing_key(routing_key: str) -> str | None:
    normalized = routing_key.replace("/", ".")
    parts = normalized.split(".")
    if len(parts) != 3:
        return None
    prefix, sn, suffix = parts
    if prefix != "dev" or suffix != "out" or not sn:
        return None
    return sn


def decode_output_payload(
    payload: bytes | str | dict[str, Any],
) -> DeviceOutputEnvelope:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        payload = json.loads(payload)
    return DeviceOutputEnvelope.model_validate(payload)


async def handle_device_output_message(
    *,
    routing_key: str,
    payload: bytes | str | dict[str, Any],
    session_registry: DiagnosticsSessionRegistry = registry,
) -> bool:
    sn = extract_sn_from_output_routing_key(routing_key)
    if sn is None:
        log.warning("Drop diagnostics output with invalid routing_key=%s", routing_key)
        return False

    try:
        envelope = decode_output_payload(payload)
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exc:
        log.warning("Drop invalid diagnostics output from sn=%s: %s", sn, exc)
        return False

    delivered = await session_registry.route_output(sn, envelope)
    if not delivered:
        log.debug(
            "Drop diagnostics output without active session: sn=%s session_id=%s seq=%s",
            sn,
            envelope.session_id,
            envelope.seq,
        )
    return delivered
