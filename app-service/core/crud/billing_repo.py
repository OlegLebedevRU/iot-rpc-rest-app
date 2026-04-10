import math
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging_config import setup_module_logger
from core.models.billing import (
    BillingCoefficient,
    BillingCounter,
    BillingActiveDevice,
)

log = setup_module_logger(__name__, "repo_billing.log")


def _current_period() -> tuple[date, date]:
    """Return (period_start, period_end) for the current calendar month."""
    today = date.today()
    period_start = today.replace(day=1)
    if period_start.month == 12:
        period_end = period_start.replace(year=period_start.year + 1, month=1)
    else:
        period_end = period_start.replace(month=period_start.month + 1)
    return period_start, period_end


class BillingRepo:
    """Data-access layer for billing tables."""

    # ──────────────────────────────── counters ────────────────────────────────

    @classmethod
    async def increment_api_requests(
        cls,
        session: AsyncSession,
        org_id: int,
        value: int = 1,
        commit: bool = True,
    ) -> None:
        ps, pe = _current_period()
        stmt = (
            insert(BillingCounter)
            .values(
                org_id=org_id,
                period_start=ps,
                period_end=pe,
                api_requests=value,
            )
            .on_conflict_do_update(
                constraint="uq_billing_counters_org_period",
                set_={"api_requests": BillingCounter.api_requests + value},
            )
        )
        await session.execute(stmt)
        if commit:
            await session.commit()

    @classmethod
    async def increment_evt_messages(
        cls,
        session: AsyncSession,
        org_id: int,
        value: int = 1,
        commit: bool = True,
    ) -> None:
        ps, pe = _current_period()
        stmt = (
            insert(BillingCounter)
            .values(
                org_id=org_id,
                period_start=ps,
                period_end=pe,
                evt_messages=value,
            )
            .on_conflict_do_update(
                constraint="uq_billing_counters_org_period",
                set_={"evt_messages": BillingCounter.evt_messages + value},
            )
        )
        await session.execute(stmt)
        if commit:
            await session.commit()

    @classmethod
    async def increment_res_messages(
        cls,
        session: AsyncSession,
        org_id: int,
        payload_bytes: int = 0,
        block_size: int = 2048,
        commit: bool = True,
    ) -> None:
        ps, pe = _current_period()
        blocks = max(1, math.ceil(payload_bytes / block_size))
        stmt = (
            insert(BillingCounter)
            .values(
                org_id=org_id,
                period_start=ps,
                period_end=pe,
                res_messages=1,
                res_payload_blocks=blocks,
            )
            .on_conflict_do_update(
                constraint="uq_billing_counters_org_period",
                set_={
                    "res_messages": BillingCounter.res_messages + 1,
                    "res_payload_blocks": BillingCounter.res_payload_blocks + blocks,
                },
            )
        )
        await session.execute(stmt)
        if commit:
            await session.commit()

    @classmethod
    async def record_device_activity(
        cls,
        session: AsyncSession,
        org_id: int,
        device_id: int,
        commit: bool = True,
    ) -> None:
        ps, _ = _current_period()
        stmt = (
            insert(BillingActiveDevice)
            .values(org_id=org_id, period_start=ps, device_id=device_id)
            .on_conflict_do_nothing(constraint="uq_billing_active_device")
        )
        await session.execute(stmt)
        if commit:
            await session.commit()

    # ──────────────────────────────── coefficients ────────────────────────────

    @classmethod
    async def get_effective_coefficients(
        cls, session: AsyncSession, as_of: date
    ) -> Optional[BillingCoefficient]:
        stmt = (
            select(BillingCoefficient)
            .where(BillingCoefficient.effective_from <= as_of)
            .order_by(BillingCoefficient.effective_from.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @classmethod
    async def set_coefficients(
        cls,
        session: AsyncSession,
        k1: Decimal,
        k2: Decimal,
        k3: Decimal,
        k4: Decimal,
        effective_from: date,
    ) -> BillingCoefficient:
        stmt = (
            insert(BillingCoefficient)
            .values(k1=k1, k2=k2, k3=k3, k4=k4, effective_from=effective_from)
            .on_conflict_do_update(
                constraint="uq_billing_coefficients_effective_from",
                set_={"k1": k1, "k2": k2, "k3": k3, "k4": k4},
            )
            .returning(BillingCoefficient)
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.scalar_one()

    @classmethod
    async def list_coefficients(
        cls, session: AsyncSession
    ) -> list[BillingCoefficient]:
        stmt = select(BillingCoefficient).order_by(
            BillingCoefficient.effective_from.desc()
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ──────────────────────────────── calculation ─────────────────────────────

    @classmethod
    async def count_active_devices(
        cls, session: AsyncSession, org_id: int, period_start: date
    ) -> int:
        stmt = select(func.count()).where(
            BillingActiveDevice.org_id == org_id,
            BillingActiveDevice.period_start == period_start,
        )
        result = await session.execute(stmt)
        return result.scalar_one() or 0

    @classmethod
    async def get_or_create_counter(
        cls, session: AsyncSession, org_id: int, period_start: date, period_end: date
    ) -> BillingCounter:
        stmt = (
            insert(BillingCounter)
            .values(org_id=org_id, period_start=period_start, period_end=period_end)
            .on_conflict_do_nothing(constraint="uq_billing_counters_org_period")
        )
        await session.execute(stmt)
        await session.commit()

        result = await session.execute(
            select(BillingCounter).where(
                BillingCounter.org_id == org_id,
                BillingCounter.period_start == period_start,
            )
        )
        return result.scalar_one()

    @classmethod
    async def get_all_org_ids_for_period(
        cls, session: AsyncSession, period_start: date
    ) -> list[int]:
        """Return org_ids that have any billing data for the given period."""
        q1 = select(BillingCounter.org_id).where(
            BillingCounter.period_start == period_start
        )
        q2 = select(BillingActiveDevice.org_id).where(
            BillingActiveDevice.period_start == period_start
        )
        stmt = q1.union(q2)
        result = await session.execute(stmt)
        return [row[0] for row in result.fetchall()]

    @classmethod
    async def save_calculation(
        cls,
        session: AsyncSession,
        org_id: int,
        period_start: date,
        period_end: date,
        active_devices: int,
        consumption: Decimal,
    ) -> None:
        stmt = (
            insert(BillingCounter)
            .values(
                org_id=org_id,
                period_start=period_start,
                period_end=period_end,
                active_devices=active_devices,
                consumption=consumption,
                calculated_at=func.now(),
            )
            .on_conflict_do_update(
                constraint="uq_billing_counters_org_period",
                set_={
                    "active_devices": active_devices,
                    "consumption": consumption,
                    "calculated_at": func.now(),
                },
            )
        )
        await session.execute(stmt)
        await session.commit()

    @classmethod
    async def get_counter(
        cls, session: AsyncSession, org_id: int, period_start: date
    ) -> Optional[BillingCounter]:
        stmt = select(BillingCounter).where(
            BillingCounter.org_id == org_id,
            BillingCounter.period_start == period_start,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @classmethod
    async def list_counters(
        cls, session: AsyncSession, org_id: int
    ) -> list[BillingCounter]:
        stmt = (
            select(BillingCounter)
            .where(BillingCounter.org_id == org_id)
            .order_by(BillingCounter.period_start.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
