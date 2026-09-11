from __future__ import annotations

import json
from typing import Any

from core.config import settings
from core.logging_config import setup_module_logger
from core.remote_input.schemas import (
    CtlLeaseRenew,
    InventoryGetCommand,
    KeyEventCommand,
    MouseClickCommand,
    PointerMoveCommand,
    StreamStartCommand,
    StreamStopCommand,
)
from core.topologys.declare import topic_publisher

log = setup_module_logger(__name__, "remote_input.log")

CtlCommand = (
    PointerMoveCommand
    | MouseClickCommand
    | InventoryGetCommand
    | StreamStartCommand
    | StreamStopCommand
    | KeyEventCommand
    | CtlLeaseRenew
    | Any
)


class DefaultControlPublisher:
    async def publish_control_command(
        self,
        sn: str,
        cmd: Any,
        ttl_ms: int | None = None,
    ) -> None:
        if ttl_ms is None:
            ttl_sec = getattr(cmd, "ttl_sec", 60)
            ttl_ms = int(ttl_sec * 1000)
        await send_ctl_command(sn, cmd, ttl_ms=ttl_ms)


default_control_publisher = DefaultControlPublisher()


async def send_ctl_command(
    sn: str,
    command: CtlCommand,
    ttl_ms: int,
) -> None:
    message_dict = command.model_dump(mode="json")
    payload_json = json.dumps(message_dict, ensure_ascii=False).encode("utf-8")
    payload_len = len(payload_json)

    if payload_len > settings.remote_input.max_command_payload_bytes:
        raise ValueError(
            f"Command payload size {payload_len} bytes exceeds limit of "
            f"{settings.remote_input.max_command_payload_bytes} bytes"
        )

    corr_id = getattr(command, "command_id", getattr(command, "cmd_id", None))
    corr_id_str = str(corr_id) if corr_id is not None else None

    routing_key = f"{settings.rmq.prefix_srv}.{sn}.{settings.rmq.suffix_control}"
    headers = {
        "correlationData": corr_id_str or "",
        "ctl_type": command.type,
    }

    log.debug(
        "Publishing ctl command: routing_key=%s command_id=%s type=%s expiration=%s",
        routing_key,
        corr_id_str,
        command.type,
        ttl_ms,
    )

    await topic_publisher.publish(
        routing_key=routing_key,
        message=message_dict,
        correlation_id=corr_id,
        expiration=ttl_ms,
        headers=headers,
    )
