import time
import uuid
from sqlalchemy import Integer, String, select, delete, Uuid, BigInteger, ForeignKey, update, Row, Sequence
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship, backref

from core import settings
from core.models import Base
from core.models.common import TaskStatus, TaskTTL
from core.schemas.device_tasks import TaskCreate, TaskRequest

class DevTask(Base):
    #__tablename__ = "tb_dev_tasks"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, index=True, default=uuid.uuid4)
    device_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    method_code: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[int] = mapped_column(Integer)
    payload = relationship(
        "DevTaskPayload", backref=backref("one_task_payload", cascade="all, delete-orphan")
    )
    status = relationship(
        "DevTaskStatus", backref=backref("one_task_status", cascade="all, delete-orphan")
    )
    result = relationship(
        "DevTaskResult", backref=backref("one_task_result", cascade="all, delete-orphan")
    )
class DevTaskPayload(Base):
    #__tablename__ = "tb_dev_tasks_payload"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey(DevTask.id))
    payload: Mapped[str] = mapped_column(String)
    one_task_payload = relationship("DevTask", cascade="all, delete-orphan")

class DevTaskStatus(Base):
    __tablename__ = "tb_dev_tasks_status"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey(DevTask.id), index=True)
    priority: Mapped[int] = mapped_column(Integer, index=True, default=0)
    status: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    ttl: Mapped[int] = mapped_column(Integer, default=TaskTTL.MIN_TTL)
    pending_at: Mapped[int] = mapped_column(Integer,default=0)
    one_task_status = relationship("DevTask", cascade="all, delete-orphan")


class DevTaskResult(Base):
    #__tablename__ = "tb_dev_tasks_result"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey(DevTask.id))
    result: Mapped[str] = mapped_column(String)
    one_task_result = relationship("DevTask", cascade="all, delete-orphan")

