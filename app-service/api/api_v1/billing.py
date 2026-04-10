"""Billing admin endpoints — only accessible for org_id=0."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from starlette import status

from api.api_v1.api_depends import Session_dep, Org_dep
from core import settings
from core.crud.billing_repo import BillingRepo
from core.logging_config import setup_module_logger
from core.schemas.billing import (
    BillingCoefficientCreate,
    BillingCoefficientOut,
    BillingCounterOut,
    BillingRecalculateRequest,
)
from core.services.billing import BillingService
from core.services.billing_utils import (
    coefficient_change_affects_period,
    require_billing_admin,
)

log = setup_module_logger(__name__, "api_billing.log")

router = APIRouter(
    prefix="/billing",
    tags=["Billing Admin"],
    include_in_schema=False,
)


async def _would_affect_current_month(
    session: Session_dep,
    effective_from: date,
) -> bool:
    """Return True if changing coefficients for this date would affect the current month."""
    today = date.today()
    current_month_start = today.replace(day=1)
    current_effective = await BillingRepo.get_effective_coefficients(
        session, current_month_start
    )

    if effective_from > current_month_start:
        return False

    if current_effective is None:
        return True

    return coefficient_change_affects_period(
        effective_from=effective_from,
        period_start=current_month_start,
        current_effective_from=current_effective.effective_from,
    )


# ──────────────── Coefficients ────────────────


@router.get("/coefficients", response_model=list[BillingCoefficientOut])
async def list_coefficients(
    session: Session_dep,
    org_id: Org_dep,
) -> list[BillingCoefficientOut]:
    require_billing_admin(org_id)
    rows = await BillingRepo.list_coefficients(session)
    return [BillingCoefficientOut.model_validate(r, from_attributes=True) for r in rows]


@router.put("/coefficients", response_model=BillingCoefficientOut)
async def set_coefficients(
    session: Session_dep,
    org_id: Org_dep,
    body: BillingCoefficientCreate,
) -> BillingCoefficientOut:
    require_billing_admin(org_id)

    # Cannot set or change coefficients that affect the current billing month.
    # Coefficients are resolved as "latest with effective_from <= period_start",
    # so effective_from in [current_month_start, next_month_start) would affect
    # the current month.  Only past or future-month dates are allowed.
    today = date.today()
    current_month_start = today.replace(day=1)
    if current_month_start.month == 12:
        next_month_start = current_month_start.replace(
            year=current_month_start.year + 1, month=1
        )
    else:
        next_month_start = current_month_start.replace(
            month=current_month_start.month + 1
        )

    if current_month_start <= body.effective_from < next_month_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot set coefficients effective within the current month "
                f"({current_month_start} — {next_month_start}). "
                f"Use a date before {current_month_start} for past corrections "
                f"or on/after {next_month_start} for future periods."
            ),
        )
    if await _would_affect_current_month(session, body.effective_from):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Cannot change coefficients that would affect the current billing month. "
                f"Use a date earlier than the currently effective record for {current_month_start} "
                f"or on/after {next_month_start} for future periods."
            ),
        )

    row = await BillingRepo.set_coefficients(
        session,
        k1=body.k1,
        k2=body.k2,
        k3=body.k3,
        k4=body.k4,
        effective_from=body.effective_from,
    )
    return BillingCoefficientOut.model_validate(row, from_attributes=True)


# ──────────────── Consumption ────────────────


@router.get("/consumption", response_model=BillingCounterOut | None)
async def get_consumption(
    session: Session_dep,
    org_id: Org_dep,
    target_org_id: Annotated[int, Query(description="Org to query billing for")],
    period: Annotated[
        date, Query(description="First day of the month (e.g. 2026-03-01)")
    ],
) -> BillingCounterOut | None:
    require_billing_admin(org_id)
    counter = await BillingRepo.get_counter(session, target_org_id, period)
    if counter is None:
        return None
    return BillingCounterOut.model_validate(counter, from_attributes=True)


@router.get("/consumption/history", response_model=list[BillingCounterOut])
async def get_consumption_history(
    session: Session_dep,
    org_id: Org_dep,
    target_org_id: Annotated[int, Query(description="Org to query billing for")],
) -> list[BillingCounterOut]:
    require_billing_admin(org_id)
    rows = await BillingRepo.list_counters(session, target_org_id)
    return [BillingCounterOut.model_validate(r, from_attributes=True) for r in rows]


# ──────────────── Recalculate ────────────────


@router.post("/recalculate")
async def recalculate(
    session: Session_dep,
    org_id: Org_dep,
    body: BillingRecalculateRequest,
) -> dict:
    require_billing_admin(org_id)

    period_start = body.period.replace(day=1)
    if period_start.month == 12:
        period_end = period_start.replace(year=period_start.year + 1, month=1)
    else:
        period_end = period_start.replace(month=period_start.month + 1)

    count = await BillingService.calculate_period(session, period_start, period_end)
    return {"status": "ok", "orgs_processed": count, "period": str(period_start)}
