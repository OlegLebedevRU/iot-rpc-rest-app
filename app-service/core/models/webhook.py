from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Integer,
    String,
    ForeignKey,
    Boolean,
    func,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship


from core.models.base import Base

if TYPE_CHECKING:
    from core.models import Org


class OrgWebhook(Base):
    # __tablename__ = "org_webhooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tb_orgs.org_id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    headers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
        onupdate=func.current_timestamp(),
    )

    org: Mapped["Org"] = relationship(back_populates="webhooks")

    __table_args__ = (
        UniqueConstraint("org_id", "event_type", name="uq_org_id_event_type"),
    )
