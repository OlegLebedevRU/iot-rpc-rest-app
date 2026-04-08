import uuid
from typing import Annotated

from fastapi import Depends
from faststream.rabbit.fastapi import RabbitMessage
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging_config import setup_module_logger
from core.models import db_helper

Session_dep = Annotated[
    AsyncSession,
    Depends(db_helper.session_getter),
]

log = setup_module_logger(__name__, "depends_broker.log")


async def sn_getter_dep(msg: RabbitMessage) -> str:
    # log.info(
    #     "Mqtt received topic= <%s>, headers=%s",
    #     msg.raw_message.routing_key,
    #     msg.raw_message.headers,
    # )
    return msg.raw_message.routing_key[4:-4]


Sn_dep = Annotated[str, Depends(sn_getter_dep)]


def _try_parse_uuid(value) -> uuid.UUID | None:
    """Try to parse a UUID from a string or 16-byte binary value.

    Attempts string parsing first (covers standard 36-char UUID strings and
    RabbitMQ auto-converted values), then falls back to 16-byte binary parsing.
    Returns None if neither attempt succeeds.
    """
    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except (ValueError, AttributeError):
            pass
    if isinstance(value, (bytes, bytearray)) and len(value) == 16:
        try:
            return uuid.UUID(bytes=bytes(value))
        except (ValueError, AttributeError):
            pass
    return None


async def corr_id_getter_dep(msg: RabbitMessage) -> UUID4 | None:
    try:
        # 1) Native AMQP correlation_id property — covers paho native clients
        #    and RabbitMQ auto-conversions (utf8 ≤256 bytes, binary uuid, ulong).
        if msg.correlation_id:
            corr_id = _try_parse_uuid(msg.correlation_id)
            if corr_id is not None:
                log.debug("Received msg.correlation_id = %s", corr_id)
                return corr_id

        if msg.raw_message.headers is None:
            log.debug("msg.raw_message.headers is None")
        headers = msg.raw_message.headers or {}

        # 2) headers["x-correlation-id"] — RabbitMQ moves utf8 >256 bytes or
        #    arbitrary binary correlation data here.
        if "x-correlation-id" in headers:
            corr_id = _try_parse_uuid(headers["x-correlation-id"])
            if corr_id is not None:
                log.info("Received headers.x-correlation-id = %s", corr_id)
                return corr_id

        # 3) headers["correlationData"] — MQTT 5 User Property used by clients
        #    such as C# MQTTnet (.NET 4.8) that send correlationData via User
        #    Properties instead of the native CorrelationData MQTT field.
        if "correlationData" in headers:
            corr_id = _try_parse_uuid(headers["correlationData"])
            if corr_id is not None:
                log.info("Received headers.correlationData = %s", corr_id)
                return corr_id

        log.warning("Received from device no corr data, headers = %s", headers)
        corr_id = None

    except (TypeError, ValueError, KeyError) as e:
        log.warning("Received from device no corr data, exception = %s", e)
        corr_id = None
    return corr_id


Corr_id_dep = Annotated[UUID4 | None, Depends(corr_id_getter_dep)]
