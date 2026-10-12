"""Private inventory delivery; independent of tenant API webhooks."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class TerminalInventoryDelivery(Base):
    __tablename__ = "tb_terminal_inventory_deliveries"
    __table_args__ = (
        Index("ix_inventory_delivery_due", "finished_at", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_uuid: Mapped[UUID] = mapped_column(Uuid, unique=True)
    tenant_id: Mapped[int] = mapped_column(Integer)
    device_id: Mapped[int] = mapped_column(Integer)
    sn: Mapped[str] = mapped_column(String(128))
    event: Mapped[dict] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(64))
