"""Explicit orphan probes. Only readonly identity lookup touches PostgreSQL.

Rate limits are process-local: deployment totals scale with app1 worker count.
Freshness and REQ-before-EVT ordering belong to the client's nonce/deadline gate;
no cross-worker server session or task is created.
"""

import asyncio
import json
import logging
import time
from datetime import timedelta
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select

from core.config import RoutingKey, settings
from core.models import Device, DeviceOrgBind, Org
from core.schemas.channel_probe import ChannelProbeEvent, ChannelProbeRequest
from core.topologys.declare import topic_publisher

log = logging.getLogger(__name__)
PROBE_TTL_SECONDS = 10
PROBE_IDENTITY_SECONDS = 2
PROBE_MAX_BYTES = 512
PROBE_MAX_IDENTITIES = 4096
_rates: dict[str, tuple[float, int]] = {}
_global_rate = (0.0, 0)


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate probe field")
        result[key] = value
    return result


def _allow(sn: str, now: float) -> bool:
    global _global_rate
    start, count = _global_rate
    if now - start >= 1:
        start, count = now, 0
    _global_rate = (start, count + 1)
    if count >= 128:
        return False
    start, count = _rates.get(sn, (now, 0))
    if now - start >= 10:
        start, count = now, 0
    if sn not in _rates and len(_rates) >= PROBE_MAX_IDENTITIES:
        for key in [key for key, (started, _) in _rates.items() if now - started >= 10]:
            del _rates[key]
        if len(_rates) >= PROBE_MAX_IDENTITIES:
            return False
    _rates[sn] = (start, count + 1)
    return count < 64


async def _known_identity(session, sn: str) -> bool:
    query = (
        select(Device.device_id)
        .join(DeviceOrgBind, DeviceOrgBind.device_id == Device.device_id)
        .join(Org, Org.org_id == DeviceOrgBind.org_id)
        .where(
            Device.sn == sn,
            Device.is_deleted.is_(False),
            DeviceOrgBind.org_id > 0,
            Org.is_deleted.is_(False),
        )
        .limit(1)
    )
    return await session.scalar(query) is not None


async def dispatch_probe(
    msg, session, sn: str, correlation: UUID | None, *, event: bool
) -> bool:
    """Return True for ANY marked message, including rejected ones (no fallthrough)."""
    headers = getattr(msg, "headers", {}) or {}
    if "iot_probe" not in headers:
        return False
    if (
        headers["iot_probe"] != "1"
        or not isinstance(correlation, UUID)
        or not correlation.int
    ):
        return True
    if not sn or len(sn) > 127 or not sn.isascii() or not sn.isalnum():
        return True
    body = getattr(msg, "body", b"")
    started = time.monotonic()
    if (
        not isinstance(body, bytes)
        or not body
        or len(body) > PROBE_MAX_BYTES
        or not _allow(sn, started)
    ):
        return True
    try:
        raw = json.loads(body, object_pairs_hook=_unique_fields)
        if event:
            payload = ChannelProbeEvent.model_validate(raw)
            if (
                UUID(payload.request_nonce) == correlation
                or headers.get("event_type_code") != "0"
            ):
                return True
            raw_id = headers.get("dev_event_id", "")
            if (
                not isinstance(raw_id, str)
                or not raw_id.isascii()
                or not raw_id.isdigit()
            ):
                return True
            event_id = int(raw_id)
            if not 0 < event_id <= 0xFFFFFFFF:
                return True
        else:
            ChannelProbeRequest.model_validate(raw)
    except ValidationError, ValueError, TypeError:
        return True
    status = "error"
    remaining = started + PROBE_TTL_SECONDS - time.monotonic()
    if remaining <= 0:
        return True
    try:
        async with asyncio.timeout(min(PROBE_IDENTITY_SECONDS, remaining)):
            if await _known_identity(session, sn):
                status = "success"
    except Exception:
        # Valid CN-scoped probes receive the same generic refusal for unavailable
        # or unknown identity. No task/event/tenant data or successful gate leaks.
        log.warning("Transport probe identity lookup failed", exc_info=True)
    suffix = settings.rmq.suffix_event_ack if event else settings.rmq.suffix_response
    response_headers = {"iot_probe": "1", "correlationData": str(correlation)}
    if event:
        response_headers.update(event_type_code="0", dev_event_id=str(event_id))
    else:
        response_headers["method_code"] = "0"
    response = {"v": 1, "type": "channel_probe", "status": status}
    if event:
        response["request_nonce"] = payload.request_nonce
    remaining = started + PROBE_TTL_SECONDS - time.monotonic()
    if remaining <= 0:
        return True
    async with asyncio.timeout(remaining):
        await topic_publisher.publish(
            routing_key=str(
                RoutingKey(prefix=settings.rmq.prefix_srv, sn=sn, suffix=suffix)
            ),
            message=response,
            correlation_id=str(correlation),
            headers=response_headers,
            expiration=timedelta(seconds=PROBE_TTL_SECONDS),
        )
    return True
