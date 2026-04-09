import logging
import json
import uuid
from collections.abc import Mapping
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
# Keep module logging on INFO by default
log.setLevel(logging.INFO)
for handler in log.handlers:
    handler.setLevel(logging.INFO)


async def sn_getter_dep(msg: RabbitMessage) -> str:
    # log.info(
    #     "Mqtt received topic= <%s>, headers=%s",
    #     msg.raw_message.routing_key,
    #     msg.raw_message.headers,
    # )
    return msg.raw_message.routing_key[4:-4]


Sn_dep = Annotated[str, Depends(sn_getter_dep)]


def _try_parse_uuid(value: object) -> uuid.UUID | None:
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
        if len(value) == 16:
            try:
                return uuid.UUID(bytes=value.encode("latin-1"))
            except (UnicodeEncodeError, ValueError, AttributeError):
                pass
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes | bytearray) and len(value) == 16:
        try:
            return uuid.UUID(bytes=bytes(value))
        except (ValueError, AttributeError):
            pass
    return None


def _normalize_headers(*header_sources: object) -> dict[str, object]:
    """Merge and normalize headers from message containers."""
    normalized: dict[str, object] = {}

    for source in header_sources:
        if not isinstance(source, Mapping):
            continue

        for key, value in source.items():
            if isinstance(key, bytes):
                key = key.decode("utf-8", errors="replace")
            else:
                key = str(key)
            normalized[key] = value

    return normalized


def _try_extract_corr_id_from_body(body: object) -> uuid.UUID | None:
    if isinstance(body, memoryview):
        body = body.tobytes()

    if isinstance(body, bytes | bytearray):
        try:
            body = bytes(body).decode("utf-8")
        except UnicodeDecodeError:
            return None

    if not isinstance(body, str) or not body.strip():
        return None

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None

    if not isinstance(payload, dict):
        return None

    for key in ("correlationData", "CorrelationData", "correlation_data", "corr_data", "corr_id"):
        if key not in payload:
            continue

        corr_id = _try_parse_uuid(payload[key])
        if corr_id is not None:
            return corr_id

    return None


async def corr_id_getter_dep(msg: RabbitMessage) -> UUID4 | None:
    try:
        log.debug("corr_id_getter_dep: Starting extraction of correlation ID")
        #log.debug("Full message object: %s", msg)
        #log.debug("Full message dict: %s", msg.__dict__ if hasattr(msg, '__dict__') else str(msg))

        msg_headers = getattr(msg, "headers", None)
        raw_headers = getattr(msg.raw_message, "headers", None)
        if raw_headers is None:
            log.debug("msg.raw_message.headers is None")

        headers = _normalize_headers(msg_headers, raw_headers)
        log.debug("Normalized merged headers: %s", headers)

        correlation_header_keys = ("correlationData", "CorrelationData")
        log.debug(
            "Correlation ID candidates: correlationData=%r, CorrelationData=%r, x-correlation-id=%r, msg.correlation_id=%r",
            headers.get("correlationData"),
            headers.get("CorrelationData"),
            headers.get("x-correlation-id"),
            msg.correlation_id,
        )

        # 1) Highest priority: MQTT correlation data in headers.
        for header_name in correlation_header_keys:
            if header_name not in headers:
                continue

            header_value = headers[header_name]
            log.debug(
                "Checking headers[%s] = %r (type: %s)",
                header_name,
                header_value,
                type(header_value),
            )
            corr_id = _try_parse_uuid(header_value)
            if corr_id is not None:
                log.debug("Using correlation ID from headers[%s] = %s", header_name, corr_id)
                return corr_id

            log.debug("Failed to parse headers[%s]: %r", header_name, header_value)

        # 2) Next priority: x-correlation-id header.
        if "x-correlation-id" in headers:
            header_value = headers["x-correlation-id"]
            log.debug(
                "Checking headers[x-correlation-id] = %r (type: %s)",
                header_value,
                type(header_value),
            )
            corr_id = _try_parse_uuid(header_value)
            if corr_id is not None:
                log.debug("Using correlation ID from headers[x-correlation-id] = %s", corr_id)
                return corr_id

            log.debug("Failed to parse headers[x-correlation-id]: %r", header_value)

        # 3) Body fallback for MQTT->AMQP bridges that drop inbound properties.
        corr_id = _try_extract_corr_id_from_body(getattr(msg, "body", None))
        if corr_id is not None:
            log.debug("Using correlation ID from message body = %s", corr_id)
            return corr_id

        # 4) Lowest priority: native AMQP correlation_id property.
        log.debug(
            "Checking msg.correlation_id = %s (type: %s)",
            msg.correlation_id,
            type(msg.correlation_id),
        )
        if msg.correlation_id:
            corr_id = _try_parse_uuid(msg.correlation_id)
            if corr_id is not None:
                log.debug("Using correlation ID from msg.correlation_id = %s", corr_id)
                return corr_id

            log.debug("Failed to parse msg.correlation_id: %s", msg.correlation_id)

        log.debug("No correlation ID found in any supported source. Headers: %s", headers)
        corr_id = None

    except (TypeError, ValueError, KeyError) as e:
        log.debug("Exception while extracting correlation ID: %s (type: %s)", e, type(e).__name__)
        corr_id = None
    return corr_id


Corr_id_dep = Annotated[UUID4 | None, Depends(corr_id_getter_dep)]
