"""Loss-tolerant portal invalidations. Actual state is read under normal authorization."""

import asyncio
import hmac
import json
import logging
import time
from collections import OrderedDict
from uuid import UUID

from faststream.rabbit import ExchangeType, RabbitExchange
from sqlalchemy import select

from core.config import settings
from core.fs_broker import fs_router
from core.models.db_helper import db_helper
from core.models.devices import Device, DeviceOrgBind

log = logging.getLogger(__name__)
exchange = RabbitExchange("portal.changes.v1", type=ExchangeType.FANOUT, durable=True)
_pending: dict[str, set[str]] = {}
_ready = asyncio.Event()


# Quality reports can arrive every second. Publish the owner's public projection
# once per five seconds, independently of the number of browser subscribers.
_last_quality: OrderedDict[str, tuple[str, float]] = OrderedDict()
_quality: dict[str, tuple[str, bool]] = {}


def quality_changed(sn: str, stream: str, camera: bool) -> None:
    try:
        stream = str(UUID(stream))
    except ValueError, TypeError, AttributeError:
        return
    now = time.monotonic()
    previous = _last_quality.get(sn)
    if previous and previous[0] == stream and now - previous[1] < 5:
        return
    changed(sn, "quality")
    if sn not in _pending:
        return
    _quality[sn] = (stream, camera)
    _last_quality[sn] = (stream, now)
    _last_quality.move_to_end(sn)
    if len(_last_quality) > 1024:
        _last_quality.popitem(last=False)


async def public_quality(sn: str, stream: str, camera: bool) -> dict:
    if camera:
        from core.camera.quality import camera_quality

        value = await camera_quality.get(sn, stream)
    else:
        from core.remote_input.runtime_quality import runtime_quality

        value = await runtime_quality.get(sn, stream)
    # Nested native reports and pending command records are internal to IoT.
    return {
        key: item
        for key, item in value.items()
        if isinstance(item, (str, int, float, bool, type(None)))
        and key
        in {
            "available",
            "quality_revision",
            "generation",
            "requested_generation",
            "status",
            "requested_kbps",
            "applied_kbps",
            "ceiling_kbps",
            "bitrate_min_kbps",
            "source_origin",
            "persistence",
            "report_age_ms",
            "transport_available",
            "transport_age_ms",
            "transport_pressure",
            "delivery_kbps",
            "raw_replaced",
            "raster_available",
            "raster_step",
            "coded_width",
            "coded_height",
            "initial_width",
            "initial_height",
            "last_idr_bytes",
        }
    }


def changed(sn: str, kind: str) -> None:
    if sn and len(sn) <= 128 and (sn in _pending or len(_pending) < 1024):
        _pending.setdefault(sn, set()).add(kind)
        _ready.set()


async def run() -> None:
    while True:
        await _ready.wait()
        await asyncio.sleep(0.15)
        batch = _pending.copy()
        quality = _quality.copy()
        _quality.clear()
        _pending.clear()
        _ready.clear()
        try:
            async with asyncio.timeout(3):
                async with db_helper.session_factory() as db:
                    rows = (
                        await db.execute(
                            select(Device.sn, Device.device_id, DeviceOrgBind.org_id)
                            .join(
                                DeviceOrgBind,
                                DeviceOrgBind.device_id == Device.device_id,
                            )
                            .where(
                                Device.sn.in_(batch.keys()),
                                Device.is_deleted.is_(False),
                                DeviceOrgBind.org_id > 0,
                            )
                        )
                    ).all()
                for sn, device, org in rows:
                    event = {
                        "v": 1,
                        "org": org,
                        "device": device,
                        "kinds": sorted(batch[sn]),
                    }
                    if sn in quality and settings.auth.internal_service_key:
                        stream, camera = quality[sn]
                        projection = {
                            "stream": stream,
                            "at": time.time_ns() // 1000000,
                            "value": await public_quality(sn, stream, camera),
                        }
                        event["quality"] = projection
                        signed = json.dumps(
                            ["portal-quality-v1", org, device, projection],
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode()
                        event["signature"] = hmac.digest(
                            settings.auth.internal_service_key.encode(),
                            signed,
                            "sha256",
                        ).hex()
                    await fs_router.broker.publish(
                        event,
                        exchange=exchange,
                        persist=False,
                        mandatory=False,
                    )
        except Exception:
            log.warning(
                "Portal change batch unavailable; readers reconcile", exc_info=True
            )


def mark_feed(session, sn):
    from sqlalchemy import event

    key = "portal_feed_changes"
    if key not in session.info:
        session.info[key] = set()
    if not session.info.get("portal_feed_callbacks"):
        session.info["portal_feed_callbacks"] = True

        def after_commit(sess):
            if not sess.in_nested_transaction():
                for terminal in sess.info.pop(key, ()):
                    changed(terminal, "feed")

        def after_rollback(sess):
            sess.info.pop(key, None)

        event.listen(session, "after_commit", after_commit)
        event.listen(session, "after_rollback", after_rollback)
    session.info[key].add(sn)
