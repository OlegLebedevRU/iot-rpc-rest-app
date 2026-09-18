from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class DeviceProvisioning(Base):
    """Durable state and idempotency tracking for device provisioning operations."""

    __tablename__ = "tb_device_provisionings"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    operation_id: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True, nullable=False)
    contract_version: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="1.0.0")
    tenant_id: Mapped[int] = mapped_column(sa.Integer, index=True, nullable=False)
    terminal_id: Mapped[int] = mapped_column(sa.Integer, index=True, nullable=False)
    sn: Mapped[str] = mapped_column(sa.String(64), index=True, nullable=False)
    device_id: Mapped[int] = mapped_column(sa.Integer, index=True, nullable=False)
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="requested", index=True)
    correlation_id: Mapped[str | None] = mapped_column(sa.String(64), index=True, nullable=True)
    requested_by_user_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    payload_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    provisioning_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=sa.text("now()"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=sa.text("now()"),
        nullable=False,
    )
    provisioned_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        sa.Index("ix_tb_device_provisionings_tenant_terminal", "tenant_id", "terminal_id"),
    )
