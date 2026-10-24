"""Persistent per-terminal fences, counters, boot retirement and bounded queues."""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class CameraAuthority(Base):
    __tablename__ = "tb_camera_authorities"

    sn: Mapped[str] = mapped_column(String(), primary_key=True)
    state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    owner: Mapped[str | None] = mapped_column(String(128))
    owner_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
