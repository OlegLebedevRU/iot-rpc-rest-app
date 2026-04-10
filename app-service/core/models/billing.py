from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Integer,
    BigInteger,
    Date,
    Numeric,
    UniqueConstraint,
    Index,
    func,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class BillingCoefficient(Base):
    __tablename__ = "tb_billing_coefficients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    k1: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=10000)
    k2: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=1)
    k3: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=1)
    k4: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=1)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("effective_from", name="uq_billing_coefficients_effective_from"),
    )


class BillingCounter(Base):
    __tablename__ = "tb_billing_counters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    active_devices: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    api_requests: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    evt_messages: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    res_messages: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    res_payload_blocks: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    consumption: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    calculated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("org_id", "period_start", name="uq_billing_counters_org_period"),
        Index("ix_billing_counters_period_start", "period_start"),
    )


class BillingActiveDevice(Base):
    __tablename__ = "tb_billing_active_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    device_id: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "org_id", "period_start", "device_id", name="uq_billing_active_device"
        ),
        Index("ix_billing_active_devices_period", "org_id", "period_start"),
    )
