from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class OrgReservation(Base):
    """Durable identity for an org ID allocated by an external service."""

    __tablename__ = "tb_org_reservations"

    operation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_project: Mapped[str] = mapped_column(String(64), nullable=False)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tb_orgs.org_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("org_id", name="tb_org_reservations_org_uq"),)
