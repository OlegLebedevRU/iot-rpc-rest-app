"""Allowlisted, restart-safe internal HTTP delivery, separate from public webhooks."""

import asyncio
import logging
import time
from datetime import timedelta
from uuid import UUID

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core import settings
from core.models import DevEvent, db_helper
from core.models.devices import Device, DeviceOrgBind
from core.models.terminal_inventory_delivery import TerminalInventoryDelivery

log = logging.getLogger(__name__)
INTERNAL_EVENT_CODES = frozenset({75})


async def enqueue_inventory(
    session: AsyncSession,
    *,
    device_id: int,
    payload: dict,
    correlation_data: UUID | str | None,
) -> None:
    """Enqueue with the event transaction; ownership comes exclusively from IoT DB."""
    if payload.get("200") not in INTERNAL_EVENT_CODES:
        return
    try:
        event_uuid = UUID(str(correlation_data))
        properties = payload["300"]
        if (
            not isinstance(properties, list)
            or len(properties) != 1
            or not isinstance(properties[0], dict)
            or not properties[0].get("445")
            or properties[0].get("440") != "l4con"
        ):
            raise ValueError("invalid inventory")
        if (
            payload.get("correlationData")
            and UUID(payload["correlationData"]) != event_uuid
        ):
            raise ValueError("correlation mismatch")
    except ValueError, TypeError, KeyError:
        log.warning(
            "Internal inventory rejected device_id=%s reason=invalid_envelope",
            device_id,
        )
        return
    owner = (
        await session.execute(
            select(DeviceOrgBind.org_id, Device.sn)
            .join(Device, Device.device_id == DeviceOrgBind.device_id)
            .where(
                Device.device_id == device_id,
                DeviceOrgBind.org_id > 0,
                Device.is_deleted.is_(False),
            )
        )
    ).one_or_none()
    if owner is None or properties[0].get("324") != owner.sn:
        log.warning(
            "Internal inventory rejected device_id=%s reason=identity", device_id
        )
        return
    event = {**payload, "correlationData": str(event_uuid)}
    await session.execute(
        insert(TerminalInventoryDelivery)
        .values(
            event_uuid=event_uuid,
            tenant_id=owner.org_id,
            device_id=device_id,
            sn=owner.sn,
            event=event,
        )
        .on_conflict_do_nothing(index_elements=[TerminalInventoryDelivery.event_uuid])
    )


async def deliver_one(session: AsyncSession) -> bool:
    row = (
        await session.execute(
            select(TerminalInventoryDelivery, func.clock_timestamp())
            .where(
                TerminalInventoryDelivery.finished_at.is_(None),
                TerminalInventoryDelivery.next_attempt_at <= func.clock_timestamp(),
            )
            .order_by(
                TerminalInventoryDelivery.next_attempt_at, TerminalInventoryDelivery.id
            )
            .limit(1)
            .with_for_update(of=TerminalInventoryDelivery, skip_locked=True)
        )
    ).one_or_none()
    if row is None:
        return False
    delivery, now = row
    # Rebinding invalidates a queued event; never deliver old tenant data to a new owner.
    owner = (
        await session.execute(
            select(DeviceOrgBind.org_id, Device.sn)
            .join(Device, Device.device_id == DeviceOrgBind.device_id)
            .where(Device.device_id == delivery.device_id, Device.is_deleted.is_(False))
        )
    ).one_or_none()
    if owner is None or owner.org_id != delivery.tenant_id or owner.sn != delivery.sn:
        delivery.finished_at = now
        delivery.last_error = "identity_changed"
        return True
    if now - delivery.created_at >= timedelta(days=30):
        delivery.finished_at = now
        delivery.last_error = "expired"
        return True
    delivery.attempts += 1
    try:
        async with httpx.AsyncClient(
            timeout=5, follow_redirects=False, trust_env=False
        ) as client:
            response = await client.post(
                settings.inventory_delivery.url,
                headers={"X-Internal-Service-Key": settings.inventory_delivery.token},
                json={
                    "v": 1,
                    "tenant_id": delivery.tenant_id,
                    "device_id": delivery.device_id,
                    "sn": delivery.sn,
                    "source_revision": delivery.id,
                    "event": delivery.event,
                },
            )
            response.raise_for_status()
        delivery.finished_at = now
        delivery.last_error = None
    except (
        Exception
    ) as exc:  # noqa: BLE001 - Isolate the private worker and persist retry state.
        code = (
            exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        )
        delivery.last_error = f"http_{code}" if code else type(exc).__name__[:64]
        if (
            code is not None
            and 400 <= code < 500
            and code not in {401, 403, 404, 408, 429}
        ):
            delivery.finished_at = (
                now  # Quarantine malformed/conflicting delivery for review.
            )
        else:
            delivery.next_attempt_at = now + timedelta(
                seconds=min(3600, 5 * 2 ** min(delivery.attempts, 10))
            )
        log.warning(
            "Internal inventory delivery id=%s attempt=%s error=%s",
            delivery.id,
            delivery.attempts,
            delivery.last_error,
        )
    return True


async def bootstrap_inventory() -> None:
    """Replay only latest event75 per currently bound identity, directly from DB once at startup."""
    after_device = 0
    while True:
        async with db_helper.session_factory() as session:
            events = list(
                (
                    await session.scalars(
                        select(DevEvent)
                        .join(
                            DeviceOrgBind, DeviceOrgBind.device_id == DevEvent.device_id
                        )
                        .where(
                            DevEvent.event_type_code == 75,
                            DevEvent.org_id == DeviceOrgBind.org_id,
                            DevEvent.device_id > after_device,
                            DevEvent.org_id > 0,
                        )
                        .distinct(DevEvent.device_id)
                        .order_by(DevEvent.device_id, DevEvent.id.desc())
                        .limit(500)
                    )
                ).all()
            )
            if not events:
                return
            for event in events:
                after_device = max(after_device, event.device_id)
                await enqueue_inventory(
                    session,
                    device_id=event.device_id,
                    payload=event.payload,
                    correlation_data=event.payload.get("correlationData"),
                )
            await session.commit()


async def delivery_loop() -> None:
    try:
        async with asyncio.timeout(60):
            await bootstrap_inventory()
    except (
        Exception
    ) as exc:  # noqa: BLE001 - Replay cannot prevent application startup or public delivery.
        log.error("Internal inventory bootstrap failed: %s", type(exc).__name__)
    last_cleanup = 0.0
    while True:
        if settings.inventory_delivery.url and settings.inventory_delivery.token:
            try:
                if time.monotonic() - last_cleanup > 3600:
                    async with db_helper.session_factory() as session:
                        old = (
                            select(TerminalInventoryDelivery.id)
                            .where(
                                TerminalInventoryDelivery.finished_at
                                < func.now() - timedelta(days=90)
                            )
                            .order_by(TerminalInventoryDelivery.finished_at)
                            .limit(1000)
                        )
                        await session.execute(
                            delete(TerminalInventoryDelivery).where(
                                TerminalInventoryDelivery.id.in_(old)
                            )
                        )
                        await session.commit()
                    last_cleanup = time.monotonic()
                for _ in range(20):
                    async with db_helper.session_factory() as session:
                        async with session.begin():
                            if not await deliver_one(session):
                                break
            except (
                Exception
            ) as exc:  # noqa: BLE001 - Isolate the private worker and persist retry state.
                log.error("Internal inventory worker failed: %s", type(exc).__name__)
        await asyncio.sleep(2)
