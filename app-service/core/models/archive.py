from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class FinArchiveBatch(Base):
    """Registry table for monthly archive batches matching shared/etranprocessing_db contract."""

    __tablename__ = "fin_archive_batches"

    id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    source_project: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    source_month: Mapped[str] = mapped_column(sa.String(7), nullable=False, index=True)
    manifest_version: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, default="1.0.0"
    )
    schema_version: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, default="1.0.0"
    )
    state: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default="prepared", index=True
    )
    total_records: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, default=0)
    data_size_bytes: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, default=0
    )
    sha256_checksum: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    min_occurred_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    max_occurred_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    through_cursor: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    consumers_passed_cursor: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, default=0
    )
    manifest_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=sa.text("now()"),
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    purged_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    error_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
