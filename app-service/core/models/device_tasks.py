import os
import time
import uuid
from typing import Any

from sqlalchemy import Column, Integer, String, select, delete, Uuid, BigInteger, ForeignKey, update, Row, Sequence
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from core.models import Base
from core.models.const import TaskStatus, TaskTTL
from core.schemas.device_tasks import TaskCreate, TaskRequest


class Device(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(Integer, unique=True)
    sn: Mapped[str] = mapped_column(String,default="default serial number")
    #__tablename__ = "tb_devices"
    # id = Column(Integer, primary_key=True)
    # device_id = Column(Integer, unique=True)
    # sn = Column(String, unique=True, default="default serial number")

    @classmethod
    async def get_device_sn(cls, session: AsyncSession, device_id: int | None = 0) -> str | None:
        data = await session.execute(select(cls.sn.label('sn'))
                                     .where(cls.device_id == device_id))
        r = data.first()
        if r:
            resp = r[0]
        else:
            resp = None
        return resp


class PersistentVariable(Base):
    #__tablename__ = "tb_variables"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    var_key: Mapped[str] = mapped_column(String, nullable=False)
    var_val: Mapped[str] = mapped_column(String, default="NULL")
    var_typ: Mapped[str] = mapped_column(String, default="STR")

    @classmethod
    async def get_data(cls, session: AsyncSession, key_val: str | None = "DEFAULT") -> Any:
        data = await session.execute(select(cls.var_val.label('var_val'), cls.var_typ.label('var_typ'))
                                     .where(cls.var_key == key_val))
        r = data.first()
        if r:
            resp = r[0]
        else:
            resp = "NULL"
        return resp

    @classmethod
    async def upsert_data(cls, session: AsyncSession,
                          key_val: str | None = "DEFAULT",
                          val_var: str | None = "NULL",
                          val_typ: str | None = "STR"
                          ):
        await session.execute(delete(cls)
                              .where(cls.var_key == key_val))
        await session.flush()
        await session.commit()
        var = cls(var_key=key_val, var_val=val_var, var_typ=val_typ)
        session.add(var)
        await session.flush()
        await session.commit()
        pass


class DevTask(Base):
    #__tablename__ = "tb_dev_tasks"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, index=True, default=uuid.uuid4)
    device_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)

    type: Mapped[int] = mapped_column(Integer, default=0)
    create_ns: Mapped[int] = mapped_column(BigInteger)


class DevTaskPayload(Base):
    #__tablename__ = "tb_dev_tasks_payload"
    id = Column(Integer, primary_key=True)
    task_id = Column(Uuid, ForeignKey("tb_dev_tasks.id"))
    payload = Column(String)


class DevTaskStatus(Base):
    __tablename__ = "tb_dev_tasks_status"
    id = Column(Integer, primary_key=True)
    task_id = Column(Uuid, ForeignKey(DevTask.id), index=True)
    priority = Column(Integer, index=True, default=0)
    status = Column(Integer, index=True, nullable=False)
    ttl = Column(Integer, default=TaskTTL.MIN_TTL)

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
    __tablename__ = "tb_dev_tasks_result"
    id = Column(Integer, primary_key=True)
    task_id = Column(Uuid, ForeignKey("tb_dev_tasks.id"))
    result = Column(String)


# .limit(os.getenv('DATABASE_LIMIT_TASKS_RESULT')))


class TaskRepository:
    @classmethod
    async def create_task(cls, session: AsyncSession, task: TaskCreate) -> DevTask:
        db_uuid = uuid.uuid4()
        db_time_ns = time.time_ns()
        db_task = DevTask(id=db_uuid, create_ns=db_time_ns,
                             **task.model_dump(include={'device_id', 'type'}))  # item.model_dump()
        db_task_payload = DevTaskPayload(task_id=db_uuid, **task.model_dump(mode='json', include={'payload'}))

        # return db_task
        db_task_status = DevTaskStatus(task_id=db_uuid, status=TaskStatus.READY,
                                          **task.model_dump(include={'ttl', 'priority'}))
        session.add(db_task)
        session.add(db_task_payload)
        session.add(db_task_status)
        await session.flush()
        await session.commit()
        # db.refresh(db_task)
        # db.refresh(db_task_payload)
        # db.refresh(db_task_status)
        return db_task

    @classmethod
    async def get_task(cls, session: AsyncSession, id: TaskRequest) -> Row[tuple[
        str, int, int, int, int, int, str]] | None:
        task = await session.execute(select(DevTaskResult.id.label('id'), DevTaskResult.type.label('type'),
                                            DevTaskResult.device_id.label('device_id'),
                                            DevTaskStatus.priority.label('priority'),
                                            DevTaskStatus.status.label('status'), DevTaskStatus.ttl.label('ttl'),
                                            DevTaskResult.result.label('result'))
                                     .where(DevTaskResult.id == id.id)
                                     .join(DevTaskStatus, DevTaskResult.id == DevTaskStatus.task_id)
                                     .join(DevTaskResult, DevTaskResult.id == DevTaskResult.task_id, isouter=True))
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
