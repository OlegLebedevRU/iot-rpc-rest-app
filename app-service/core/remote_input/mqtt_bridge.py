from __future__ import annotations

import json
from typing import Any

from core.config import settings
from core.logging_config import setup_module_logger
from core.remote_input.leases import (
    LeaseRegistryProtocol,
    lease_registry,
)
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


class AgentOnlineStatus:
    def __init__(self, online: bool = False) -> None:
        self.online = online

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def __setitem__(self, item: str, value: Any) -> None:
        setattr(self, item, value)

    def __repr__(self) -> str:
        return f"AgentOnlineStatus(online={self.online})"


class SnStatus:
    def __init__(self, online: bool = False) -> None:
        self.agent = AgentOnlineStatus(online=online)

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def __setitem__(self, item: str, value: Any) -> None:
        setattr(self, item, value)

    def __repr__(self) -> str:
        return f"SnStatus(agent={self.agent})"


_SN_STATUS: dict[str, SnStatus] = {}


def extract_sn_from_ctl_routing_key(routing_key: str) -> str | None:
    normalized = routing_key.replace("/", ".")
    parts = normalized.split(".")
    if len(parts) != 3:
        return None
    prefix, sn, suffix = parts
    if prefix != "dev" or suffix != settings.rmq.suffix_control or not sn:
        return None
    return sn


def _extract_malformed_ctl_diagnostics(
    payload: bytes | str | dict[str, Any],
) -> dict[str, Any]:
    try:
        raw_dict: dict[str, Any] | None = None
        if isinstance(payload, dict):
            raw_dict = payload
        elif isinstance(payload, bytes):
            raw_dict = json.loads(payload.decode("utf-8", errors="replace"))
        elif isinstance(payload, str):
            raw_dict = json.loads(payload)
        if isinstance(raw_dict, dict):
            cmd_type = raw_dict.get("type")
            cmd_id = raw_dict.get("command_id")
            terminal_time = raw_dict.get("terminal_time_ms")
            reason = "invalid_payload"
            if cmd_type in ("ack", "nack"):
                if cmd_id is None or (isinstance(cmd_id, str) and not cmd_id.strip()):
                    reason = "empty_command_id"
                else:
                    reason = "invalid_command_id_uuid"
            return {
                "type": cmd_type or "unknown",
                "command_id": str(cmd_id)[:64] if cmd_id is not None else "<none>",
                "terminal_time_ms": terminal_time
                if isinstance(terminal_time, int)
                else None,
                "reason": reason,
            }
    except Exception:
        pass
    return {
        "reason": "unparseable_json",
        "type": "unknown",
        "command_id": "<none>",
        "terminal_time_ms": None,
    }


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
    l_registry: LeaseRegistryProtocol = lease_registry,
) -> bool:
    try:
        sn = extract_sn_from_ctl_routing_key(routing_key)
        if sn is None:
            log.warning("Drop ctl message with invalid routing_key=%s", routing_key)
            return False

        try:
            envelope = decode_ctl_payload(payload)
        except Exception as exc:
            diag = _extract_malformed_ctl_diagnostics(payload)
            log.warning(
                "Drop invalid ctl payload from sn=%s: reason=%s command_type=%s command_id=%s latency_ms=%s transport=mqtt error=%s",
                sn,
                diag.get("reason"),
                diag.get("type"),
                diag.get("command_id"),
                diag.get("terminal_time_ms"),
                exc,
            )
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
                    resolved = await cmd_registry.resolve(
                        envelope.command_id, res, lease_id=envelope.lease_id
                    )
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
                    applied_deadline_ms=envelope.applied_deadline_ms,
                    expires_at_ms=envelope.expires_at_ms,
                )
                resolved = await cmd_registry.resolve(
                    envelope.command_id, res, lease_id=envelope.lease_id
                )
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
                resolved = await cmd_registry.resolve(
                    envelope.command_id, res, lease_id=envelope.lease_id
                )
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
            is_online = (envelope.status == "online") or (
                getattr(envelope, "online", None) is True
            )
            if is_online:
                if sn not in _SN_STATUS:
                    _SN_STATUS[sn] = SnStatus(online=True)
                else:
                    _SN_STATUS[sn].agent.online = True

            changed, view = await p_registry.update(sn, envelope)
            if sn not in _SN_STATUS:
                _SN_STATUS[sn] = SnStatus(online=view.online)
            else:
                _SN_STATUS[sn].agent.online = view.online
            return True

        elif isinstance(envelope, CtlStreamEvent):
            if envelope.sn is not None and envelope.sn != sn:
                log.warning(
                    "CtlStreamEvent SN mismatch: topic_sn=%s payload_sn=%s. Using topic_sn.",
                    sn,
                    envelope.sn,
                )
            if envelope.state in (
                "stopped",
                "failed",
                "source_unavailable",
                "session_unavailable",
            ):
                active_lease = await l_registry.get_active_by_sn(sn)
                if active_lease:
                    if (
                        active_lease.stream_instance_id is None
                        or envelope.stream_instance_id is None
                        or active_lease.stream_instance_id
                        == envelope.stream_instance_id
                    ):
                        active_lease.stream_state = "stopped"
                        active_lease.stream_instance_id = None
                        active_lease.stream_mode = None
                        active_lease.selected_desktop_id = None
                        active_lease.selected_session_id = None
                        active_lease.selected_camera_id = None
                        log.info(
                            "Cleared lease stream state on %s event: sn=%s lease_id=%s stream_instance_id=%s reason=%s",
                            envelope.state,
                            sn,
                            active_lease.lease_id,
                            envelope.stream_instance_id,
                            envelope.reason,
                        )
                    else:
                        log.info(
                            "Ignored stale %s stream_event for sn=%s (event_instance=%s != active_lease_instance=%s)",
                            envelope.state,
                            sn,
                            envelope.stream_instance_id,
                            active_lease.stream_instance_id,
                        )
            elif envelope.state == "running":
                active_lease = await l_registry.get_active_by_sn(sn)
                if active_lease:
                    active_lease.stream_state = "running"
                    if envelope.stream_instance_id is not None:
                        active_lease.stream_instance_id = envelope.stream_instance_id
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
