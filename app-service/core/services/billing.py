from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from core import settings
from core.crud.billing_repo import BillingRepo
from core.logging_config import setup_module_logger

log = setup_module_logger(__name__, "srv_billing.log")


def _period_for(target: date) -> tuple[date, date]:
    """Return (period_start, period_end) for the month that *target* falls in."""
    period_start = target.replace(day=1)
    if period_start.month == 12:
        period_end = period_start.replace(year=period_start.year + 1, month=1)
    else:
        period_end = period_start.replace(month=period_start.month + 1)
    return period_start, period_end


def _previous_period() -> tuple[date, date]:
    """Return (period_start, period_end) for the previous calendar month."""
    today = date.today()
    first_of_current = today.replace(day=1)
    last_of_prev = first_of_current - timedelta(days=1)
    return _period_for(last_of_prev)


class BillingService:
    """Orchestrates billing calculations and counter operations."""

    @classmethod
    async def calculate_period(
        cls, session: AsyncSession, period_start: date, period_end: date
    ) -> int:
        """
        Calculate consumption for all orgs that had activity in [period_start, period_end).
        Returns the number of orgs processed.
        """
        coeff = await BillingRepo.get_effective_coefficients(session, period_start)
        if coeff is None:
            k1 = Decimal(str(settings.billing.default_k1))
            k2 = Decimal(str(settings.billing.default_k2))
            k3 = Decimal(str(settings.billing.default_k3))
            k4 = Decimal(str(settings.billing.default_k4))
            log.warning(
                "No coefficients found for period %s, using defaults: k1=%s k2=%s k3=%s k4=%s",
                period_start, k1, k2, k3, k4,
            )
        else:
            k1, k2, k3, k4 = coeff.k1, coeff.k2, coeff.k3, coeff.k4

        org_ids = await BillingRepo.get_all_org_ids_for_period(session, period_start)
        if not org_ids:
            log.info("No orgs with activity for period %s", period_start)
            return 0

        count = 0
        for org_id in org_ids:
            active_devices = await BillingRepo.count_active_devices(
                session, org_id, period_start
            )

            counter = await BillingRepo.get_counter(session, org_id, period_start)
            api_requests = counter.api_requests if counter else 0
            evt_messages = counter.evt_messages if counter else 0
            res_payload_blocks = counter.res_payload_blocks if counter else 0

            p1 = Decimal(active_devices) * k1
            p2 = Decimal(api_requests) * k2
            p3 = Decimal(evt_messages) * k3
            p4 = Decimal(res_payload_blocks) * k4

            consumption = p1 + p2 + p3 + p4

            await BillingRepo.save_calculation(
                session,
                org_id=org_id,
                period_start=period_start,
                period_end=period_end,
                active_devices=active_devices,
                consumption=consumption,
            )
            log.info(
                "Billing calculated: org_id=%d period=%s P1=%s P2=%s P3=%s P4=%s total=%s",
                org_id, period_start, p1, p2, p3, p4, consumption,
            )
            count += 1

        return count

    @classmethod
    async def calculate_previous_month(cls, session: AsyncSession) -> int:
        """Calculate billing for the previous calendar month."""
        period_start, period_end = _previous_period()
        return await cls.calculate_period(session, period_start, period_end)

    @classmethod
    async def handle_billing_event(
        cls,
        session: AsyncSession,
        org_id: int,
        device_id: int,
        counter_type: str,
        value: int = 1,
        payload_bytes: int = 0,
    ) -> None:
        """Process a single billing event from the RMQ queue."""
        try:
            has_changes = False
            # Always record device activity
            if device_id > 0:
                await BillingRepo.record_device_activity(
                    session, org_id, device_id, commit=False
                )
                has_changes = True

            if counter_type == "evt":
                await BillingRepo.increment_evt_messages(
                    session, org_id, value, commit=False
                )
                has_changes = True
            elif counter_type == "res":
                await BillingRepo.increment_res_messages(
                    session,
                    org_id,
                    payload_bytes=payload_bytes,
                    block_size=settings.billing.block_size,
                    commit=False,
                )
                has_changes = True
            elif counter_type == "api":
                await BillingRepo.increment_api_requests(
                    session, org_id, value, commit=False
                )
                has_changes = True
            elif counter_type == "activity":
                pass  # device activity already recorded above
            else:
                log.warning("Unknown billing counter_type: %s", counter_type)
            if has_changes:
                await session.commit()
        except Exception as e:
            await session.rollback()
            log.error(
                "Billing event processing error: org_id=%d device_id=%d type=%s error=%s",
                org_id, device_id, counter_type, e,
            )
