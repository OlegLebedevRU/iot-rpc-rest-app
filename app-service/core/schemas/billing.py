from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class BillingCounterOut(BaseModel):
    org_id: int
    period_start: date
    period_end: date
    active_devices: int = 0
    api_requests: int = 0
    evt_messages: int = 0
    res_messages: int = 0
    res_payload_blocks: int = 0
    consumption: Optional[Decimal] = None
    calculated_at: Optional[datetime] = None


class BillingCoefficientOut(BaseModel):
    id: int
    k1: Decimal
    k2: Decimal
    k3: Decimal
    k4: Decimal
    effective_from: date
    created_at: datetime


class BillingCoefficientCreate(BaseModel):
    k1: Decimal = Field(default=Decimal("10000"), ge=0)
    k2: Decimal = Field(default=Decimal("1"), ge=0)
    k3: Decimal = Field(default=Decimal("1"), ge=0)
    k4: Decimal = Field(default=Decimal("1"), ge=0)
    effective_from: date


class BillingRecalculateRequest(BaseModel):
    period: date = Field(
        ..., description="First day of the month to recalculate (e.g. 2026-03-01)"
    )


class BillingEvent(BaseModel):
    """Message published to the billing queue for counter increments."""

    org_id: int
    device_id: int
    counter_type: str = Field(
        ...,
        description="One of: evt, res, api, activity",
    )
    value: int = Field(default=1, description="Increment value")
    payload_bytes: int = Field(
        default=0, description="Payload size in bytes (for res messages)"
    )
