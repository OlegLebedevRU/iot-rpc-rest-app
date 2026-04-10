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

log = setup_module_logger(__name__, "api_billing.log")

router = APIRouter(
    prefix="/billing",
    tags=["Billing Admin"],
    include_in_schema=False,
)


def _require_admin(org_id: int) -> None:
    """Raise 403 if org_id is not 0 (admin)."""
    if org_id != 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Billing admin endpoints are only accessible for org_id=0",
        )


# ──────────────── Coefficients ────────────────


@router.get("/coefficients", response_model=list[BillingCoefficientOut])
async def list_coefficients(
    session: Session_dep,
    org_id: Org_dep,
) -> list[BillingCoefficientOut]:
    _require_admin(org_id)
    rows = await BillingRepo.list_coefficients(session)
    return [BillingCoefficientOut.model_validate(r, from_attributes=True) for r in rows]


@router.put("/coefficients", response_model=BillingCoefficientOut)
async def set_coefficients(
    session: Session_dep,
    org_id: Org_dep,
    body: BillingCoefficientCreate,
) -> BillingCoefficientOut:
    _require_admin(org_id)

    # Cannot change coefficients for the current month
    today = date.today()
    current_month_start = today.replace(day=1)
    if body.effective_from >= current_month_start:
        next_month_start = (
            current_month_start.replace(month=current_month_start.month + 1)
            if current_month_start.month < 12
            else current_month_start.replace(year=current_month_start.year + 1, month=1)
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot set coefficients for current or future month starting from {current_month_start}. "
            f"Earliest allowed effective_from is a past date before {current_month_start}. "
            f"For next billing period, use effective_from on or after the first of a future month.",
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
    _require_admin(org_id)
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
    _require_admin(org_id)
    rows = await BillingRepo.list_counters(session, target_org_id)
    return [BillingCounterOut.model_validate(r, from_attributes=True) for r in rows]


# ──────────────── Recalculate ────────────────


@router.post("/recalculate")
async def recalculate(
    session: Session_dep,
    org_id: Org_dep,
    body: BillingRecalculateRequest,
) -> dict:
    _require_admin(org_id)

    period_start = body.period.replace(day=1)
    if period_start.month == 12:
        period_end = period_start.replace(year=period_start.year + 1, month=1)
    else:
        period_end = period_start.replace(month=period_start.month + 1)

    count = await BillingService.calculate_period(session, period_start, period_end)
    return {"status": "ok", "orgs_processed": count, "period": str(period_start)}
