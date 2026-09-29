import uuid
from datetime import datetime
from sqlalchemy import (
    Integer,
    String,
    Uuid,
    ForeignKey,
    Boolean,
    func,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.models import Base
from core.models.common import TaskTTL


class DevTask(Base):
    # __tablename__ = "tb_dev_tasks"
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    device_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    method_code: Mapped[int] = mapped_column(Integer, default=0)
    ext_task_id: Mapped[str] = mapped_column(String, nullable=True)
    created_at = mapped_column(
        TIMESTAMP(timezone=True, precision=0),
        server_default=func.current_timestamp(0),
        default=None,
        index=True,
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    payload: Mapped["DevTaskPayload"] = relationship(back_populates="one_task_payload")
    status: Mapped["DevTaskStatus"] = relationship(back_populates="one_task_status")
    results: Mapped[list["DevTaskResult"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class DevTaskPayload(Base):
    # __tablename__ = "tb_dev_tasks_payload"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey(DevTask.id))
    payload: Mapped[dict] = mapped_column(JSONB, nullable=True)
    # Mapped[str] = mapped_column(String)
    one_task_payload: Mapped["DevTask"] = relationship(
        single_parent=True, cascade="all, delete-orphan"
    )


class DevTaskStatus(Base):
    __tablename__ = "tb_dev_tasks_status"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey(DevTask.id), index=True)
    priority: Mapped[int] = mapped_column(Integer, index=True, default=0)
    status: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    ttl: Mapped[int] = mapped_column(Integer, default=TaskTTL.MIN_TTL, index=True)
    initial_ttl: Mapped[int] = mapped_column(Integer, default=TaskTTL.MIN_TTL)
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True, index=True
    )
    pending_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    locked_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    one_task_status: Mapped["DevTask"] = relationship(
        single_parent=True, cascade="all, delete-orphan"
    )


class DevTaskResult(Base):
    __table_args__ = (
        Index(
            "uq_rpc_result_uid",
            "task_id",
            "result_uid",
            unique=True,
            postgresql_where=text("result_uid IS NOT NULL"),
        ),
        Index(
            "uq_rpc_result_fingerprint",
            "task_id",
            "result_fingerprint",
            unique=True,
            postgresql_where=text("result_fingerprint IS NOT NULL"),
        ),
    )
    # __tablename__ = "tb_dev_tasks_result"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey(DevTask.id))
    ext_id: Mapped[int] = mapped_column(Integer, default=0)
    status_code: Mapped[int] = mapped_column(Integer, default=501)
    result: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False
    )  # Изменено!
    result_uid: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    result_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task: Mapped["DevTask"] = relationship(back_populates="results")


class RpcResultWebhook(Base):
    """One durable delivery per accepted result; no payload or secret copies."""

    __tablename__ = "tb_rpc_result_webhooks"
    __table_args__ = (
        Index(
            "ix_rpc_webhook_due",
            "next_attempt_at",
            postgresql_where=text("finished_at IS NULL"),
        ),
    )
    result_id: Mapped[int] = mapped_column(
        ForeignKey(DevTaskResult.id, ondelete="CASCADE"), primary_key=True
    )
    webhook_id: Mapped[int] = mapped_column(
        ForeignKey("tb_org_webhooks.id", ondelete="CASCADE"), nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now() + interval '30 minutes'")
    )
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(64))
