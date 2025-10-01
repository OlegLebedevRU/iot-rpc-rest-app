import uuid
from datetime import datetime
from sqlalchemy import (
    Integer,
    String,
    Uuid,
    ForeignKey,
    Boolean,
    func,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
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
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    payload: Mapped["DevTaskPayload"] = relationship(back_populates="one_task_payload")
    status: Mapped["DevTaskStatus"] = relationship(back_populates="one_task_status")
    result: Mapped["DevTaskResult"] = relationship(back_populates="task_result")


class DevTaskPayload(Base):
    # __tablename__ = "tb_dev_tasks_payload"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey(DevTask.id))
    payload: Mapped[str] = mapped_column(String)
    one_task_payload: Mapped["DevTask"] = relationship(
        single_parent=True, cascade="all, delete-orphan"
    )


class DevTaskStatus(Base):
    __tablename__ = "tb_dev_tasks_status"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey(DevTask.id), index=True)
    priority: Mapped[int] = mapped_column(Integer, index=True, default=0)
    status: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    ttl: Mapped[int] = mapped_column(Integer, default=TaskTTL.MIN_TTL)
    pending_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    locked_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    one_task_status: Mapped["DevTask"] = relationship(
        single_parent=True, cascade="all, delete-orphan"
    )


class DevTaskResult(Base):
    # __tablename__ = "tb_dev_tasks_result"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey(DevTask.id))
    ext_id: Mapped[int] = mapped_column(Integer, default=0)
    status_code: Mapped[int] = mapped_column(Integer, default=501)
    result: Mapped[str] = mapped_column(String, default="default")
    task_result: Mapped["DevTask"] = relationship(
        single_parent=True, cascade="all, delete-orphan"
    )
