from __future__ import annotations

import json
from core.config import settings
from core.logging_config import setup_module_logger
from core.remote_input.schemas import MouseClickCommand, PointerMoveCommand
from core.topologys.declare import topic_publisher

log = setup_module_logger(__name__, "remote_input.log")


async def send_ctl_command(
    sn: str,
    command: PointerMoveCommand | MouseClickCommand,
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

    routing_key = f"{settings.rmq.prefix_srv}.{sn}.{settings.rmq.suffix_control}"
    headers = {
        "correlationData": str(command.command_id),
        "ctl_type": command.type,
    }

    log.debug(
        "Publishing ctl command: routing_key=%s command_id=%s type=%s expiration=%s",
        routing_key,
        command.command_id,
        command.type,
        ttl_ms,
    )

    await topic_publisher.publish(
        routing_key=routing_key,
        message=message_dict,
        correlation_id=command.command_id,
        expiration=ttl_ms,
        headers=headers,
    )
