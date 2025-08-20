import os
import time
import uuid
from sqlalchemy import Integer, String, select, delete, Uuid, BigInteger, ForeignKey, update, Row, Sequence
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from core.models import Base
from core.models.common import TaskStatus, TaskTTL
from core.schemas.device_tasks import TaskCreate, TaskRequest

class DevTask(Base):
    #__tablename__ = "tb_dev_tasks"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, index=True, default=uuid.uuid4)
    device_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    type: Mapped[int] = mapped_column(Integer, default=0)
    create_ns: Mapped[int] = mapped_column(BigInteger)

class DevTaskPayload(Base):
    #__tablename__ = "tb_dev_tasks_payload"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey(DevTask.id))
    payload: Mapped[str] = mapped_column(String)


class DevTaskStatus(Base):
    __tablename__ = "tb_dev_tasks_status"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey(DevTask.id), index=True)
    priority: Mapped[int] = mapped_column(Integer, index=True, default=0)
    status: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    ttl: Mapped[int] = mapped_column(Integer, default=TaskTTL.MIN_TTL)
    pending_ns: Mapped[int] = mapped_column(BigInteger,default=0)
    @classmethod
    async def ttl_decr(cls, session: AsyncSession, delta_ttl: int | None = 1):
        await session.execute(update(cls)
                              .where(cls.status == TaskStatus.READY)
                              .where(cls.ttl > (delta_ttl-1))
                              .values(ttl=cls.ttl - delta_ttl))
        await session.flush()
        await session.commit()
        # except OperationalError as e:
        await session.execute(update(cls)
                              .where(cls.status == TaskStatus.READY)
                              .where(cls.ttl <= (delta_ttl-1))
                              .values(status=7, ttl=0))
        await session.flush()
        await session.commit()
        return


class DevTaskResult(Base):
    #__tablename__ = "tb_dev_tasks_result"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey(DevTask.id))
    result: Mapped[str] = mapped_column(String)


# .limit(os.getenv('DATABASE_LIMIT_TASKS_RESULT')))


class TaskRepository:
    @classmethod
    async def create_task(cls, session: AsyncSession, task: TaskCreate) -> DevTask:
        db_uuid = uuid.uuid4()
        db_time_ns = time.time_ns()
        db_task = DevTask(id=db_uuid, create_ns=db_time_ns,
                             **task.model_dump(include={'device_id', 'type'}))  # item.model_dump()
        db_task_payload = DevTaskPayload(task_id=db_uuid, **task.model_dump(mode='json', include={'payload'}))
        db_task_status = DevTaskStatus(task_id=db_uuid, status=TaskStatus.READY,
                                          **task.model_dump(include={'ttl', 'priority'}))
        session.add(db_task)
        session.add(db_task_payload)
        session.add(db_task_status)
        await session.flush()
        await session.commit()
        return db_task

    @classmethod
    async def get_task(cls, session: AsyncSession, id: TaskRequest) -> Row[tuple[
        str, int, int, int, int, int, str]] | None:
        task = await session.execute(select(DevTask.id.label('id'), DevTask.type.label('type'),
                                            DevTask.device_id.label('device_id'),
                                            DevTaskStatus.priority.label('priority'),
                                            DevTaskStatus.status.label('status'), DevTaskStatus.ttl.label('ttl'),
                                            DevTaskResult.result.label('result'))
                                     .where(DevTask.id == id.id)
                                     .join(DevTaskStatus, DevTask.id == DevTaskStatus.task_id)
                                     .join(DevTaskResult, DevTask.id == DevTaskResult.task_id, isouter=True))
        resp = task.first()
        # print(resp[2])
        return resp

    @classmethod
    async def get_tasks(cls, session: AsyncSession, device_id: int | None = 0) -> Sequence[
        Row[tuple[str, int, int, int, int, int]]]:
        task = await session.execute(select(DevTask.id.label('id'), DevTask.type.label('type'),
                                            DevTask.device_id.label('device_id'),
                                            DevTaskStatus.priority.label('priority'),
                                            DevTaskStatus.status.label('status'), DevTaskStatus.ttl.label('ttl'))
                                     .where(DevTask.device_id == device_id)
                                     .join(DevTaskStatus, DevTask.id == DevTaskStatus.task_id)
                                     .limit(int(os.getenv('DATABASE_LIMIT_TASKS_RESULT', "100"))))

        return task.all()
