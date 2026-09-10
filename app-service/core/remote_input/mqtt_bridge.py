from __future__ import annotations

from typing import Any

from core.config import settings
from core.logging_config import setup_module_logger
from core.remote_input.pending import (
    PendingCommandRegistryProtocol,
    PendingResult,
    pending_registry,
)
from core.remote_input.presence import (
    PresenceRegistryProtocol,
    presence_registry,
)
from core.remote_input.schemas import (
    CtlAck,
    CtlInboundAdapter,
    CtlInboundMessage,
    CtlNack,
    CtlPresence,
    CtlStreamEvent,
)

log = setup_module_logger(__name__, "remote_input.log")


def extract_sn_from_ctl_routing_key(routing_key: str) -> str | None:
    normalized = routing_key.replace("/", ".")
    parts = normalized.split(".")
    if len(parts) != 3:
        return None
    prefix, sn, suffix = parts
    if prefix != "dev" or suffix != settings.rmq.suffix_control or not sn:
        return None
    return sn


def decode_ctl_payload(payload: bytes | str | dict[str, Any]) -> CtlInboundMessage:
    if isinstance(payload, bytes):
        if len(payload) > settings.remote_input.max_inbound_payload_bytes:
            raise ValueError(
                f"Payload size {len(payload)} bytes exceeds limit {settings.remote_input.max_inbound_payload_bytes}"
            )
        return CtlInboundAdapter.validate_json(payload)
    elif isinstance(payload, str):
        payload_bytes = payload.encode("utf-8")
        if len(payload_bytes) > settings.remote_input.max_inbound_payload_bytes:
            raise ValueError(
                f"Payload size {len(payload_bytes)} bytes exceeds limit {settings.remote_input.max_inbound_payload_bytes}"
            )
        return CtlInboundAdapter.validate_json(payload_bytes)
    elif isinstance(payload, dict):
        return CtlInboundAdapter.validate_python(payload)
    raise TypeError(f"Unsupported payload type {type(payload)}")


async def handle_device_ctl_message(
    *,
    routing_key: str,
    payload: bytes | str | dict[str, Any],
    p_registry: PresenceRegistryProtocol = presence_registry,
    cmd_registry: PendingCommandRegistryProtocol = pending_registry,
) -> bool:
    try:
        sn = extract_sn_from_ctl_routing_key(routing_key)
        if sn is None:
            log.warning("Drop ctl message with invalid routing_key=%s", routing_key)
            return False

        try:
            envelope = decode_ctl_payload(payload)
        except Exception as exc:
            log.warning("Drop invalid ctl payload from sn=%s: %s", sn, exc)
            return False

        if isinstance(envelope, (CtlAck, CtlNack)):
            if envelope.sn != sn:
                log.warning(
                    "Drop ctl %s with SN mismatch: topic_sn=%s payload_sn=%s",
                    envelope.type,
                    sn,
                    envelope.sn,
                )
                return False

            if isinstance(envelope, CtlAck):
                if envelope.result == "nack":
                    res = PendingResult(
                        result="nack",
                        code=str(envelope.code) if envelope.code else "unknown_error",
                        message=envelope.message or "",
                        terminal_time_ms=envelope.terminal_time_ms,
                    )
                    resolved = await cmd_registry.resolve(envelope.command_id, res)
                    if not resolved:
                        log.debug(
                            "Duplicate or unknown NACK for command_id=%s sn=%s code=%s",
                            envelope.command_id,
                            sn,
                            envelope.code,
                        )
                    else:
                        log.warning(
                            "NACK resolved for command_id=%s lease_id=%s sn=%s code=%s message=%s",
                            envelope.command_id,
                            envelope.lease_id,
                            sn,
                            envelope.code,
                            envelope.message,
                        )
                    return resolved

                if envelope.inventory is not None:
                    await p_registry.update_inventory(sn, envelope.inventory)

                res = PendingResult(
                    result=envelope.result,
                    terminal_time_ms=envelope.terminal_time_ms,
                    stream_instance_id=envelope.stream_instance_id,
                    state=envelope.state,
                    inventory=envelope.inventory,
                )
                resolved = await cmd_registry.resolve(envelope.command_id, res)
                if not resolved:
                    log.debug(
                        "Duplicate or unknown ACK for command_id=%s sn=%s",
                        envelope.command_id,
                        sn,
                    )
                else:
                    log.info(
                        "ACK resolved for command_id=%s lease_id=%s sn=%s result=%s",
                        envelope.command_id,
                        envelope.lease_id,
                        sn,
                        envelope.result,
                    )
                return resolved
            else:
                res = PendingResult(
                    result="nack",
                    code=str(envelope.code),
                    message=envelope.message,
                    terminal_time_ms=envelope.terminal_time_ms,
                )
                resolved = await cmd_registry.resolve(envelope.command_id, res)
                if not resolved:
                    log.debug(
                        "Duplicate or unknown NACK for command_id=%s sn=%s code=%s",
                        envelope.command_id,
                        sn,
                        envelope.code,
                    )
                else:
                    log.warning(
                        "NACK resolved for command_id=%s lease_id=%s sn=%s code=%s message=%s",
                        envelope.command_id,
                        envelope.lease_id,
                        sn,
                        envelope.code,
                        envelope.message,
                    )
                return resolved

        elif isinstance(envelope, CtlPresence):
            await p_registry.update(sn, envelope)
            return True

        elif isinstance(envelope, CtlStreamEvent):
            await p_registry.update_stream_event(sn, envelope)
            return True

        return False
    except Exception as exc:
        log.warning(
            "Unhandled exception in handle_device_ctl_message for routing_key=%s: %s",
            routing_key,
            exc,
            exc_info=True,
        )
        return False
