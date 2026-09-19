from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class RemoteSession(Base):
    __tablename__ = "tb_remote_sessions"

    __table_args__ = (
        sa.Index(
            "uq_active_remote_session_per_sn",
            "sn",
            unique=True,
            postgresql_where=sa.text("status IN ('requested', 'starting', 'active', 'stopping')"),
            sqlite_where=sa.text("status IN ('requested', 'starting', 'active', 'stopping')"),
        ),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True, nullable=False)
    tenant_id: Mapped[int] = mapped_column(sa.Integer, index=True, nullable=False)
    terminal_id: Mapped[str | None] = mapped_column(sa.String(64), index=True, nullable=True)
    device_id: Mapped[int | None] = mapped_column(sa.Integer, index=True, nullable=True)
    sn: Mapped[str] = mapped_column(sa.String(64), index=True, nullable=False)
    session_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)  # "console" | "video"
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="requested")
    requested_by_user_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    operation_id: Mapped[str | None] = mapped_column(sa.String(64), index=True, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(sa.String(64), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=sa.text("now()"),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    session_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class RemoteSessionEvent(Base):
    __tablename__ = "tb_remote_session_events"

    cursor: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True, index=True)
    event_id: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    tenant_id: Mapped[int | None] = mapped_column(sa.Integer, index=True, nullable=True)
    terminal_id: Mapped[str | None] = mapped_column(sa.String(64), index=True, nullable=True)
    device_id: Mapped[int | None] = mapped_column(sa.Integer, index=True, nullable=True)
    sn: Mapped[str] = mapped_column(sa.String(64), index=True, nullable=False)
    session_id: Mapped[str | None] = mapped_column(sa.String(64), index=True, nullable=True)
    session_type: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    event_type: Mapped[str] = mapped_column(sa.String(64), index=True, nullable=False)
    event_version: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="1.0.0")
    lifecycle_state: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    reason: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    operation_id: Mapped[str | None] = mapped_column(sa.String(64), index=True, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(sa.String(64), index=True, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=sa.text("now()"),
        nullable=False,
    )
