"""Loss-tolerant portal invalidations. Actual state is read under normal authorization."""

import asyncio
import logging

from faststream.rabbit import ExchangeType, RabbitExchange
from sqlalchemy import select

from core.fs_broker import fs_router
from core.models.db_helper import db_helper
from core.models.devices import Device, DeviceOrgBind

log = logging.getLogger(__name__)
exchange = RabbitExchange("portal.changes.v1", type=ExchangeType.FANOUT, durable=True)
_pending: dict[str, set[str]] = {}
_ready = asyncio.Event()


def changed(sn: str, kind: str) -> None:
    if sn and len(sn) <= 128 and (sn in _pending or len(_pending) < 1024):
        _pending.setdefault(sn, set()).add(kind)
        _ready.set()


async def run() -> None:
    while True:
        await _ready.wait()
        await asyncio.sleep(0.15)
        batch = _pending.copy()
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
                    await fs_router.broker.publish(
                        {
                            "v": 1,
                            "org": org,
                            "device": device,
                            "kinds": sorted(batch[sn]),
                        },
                        exchange=exchange,
                        persist=False,
                        mandatory=False,
                    )
        except Exception:  # noqa: BLE001 - A best-effort hint must not block device ingestion.
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
