import time
import uuid
from typing import List

from sqlalchemy import Sequence, Row, select, update
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import Mapped

from core import settings
from core.models.common import TaskStatus
from core.models.device_tasks import DevTaskStatus, DevTask, DevTaskResult, DevTaskPayload
from core.schemas.device_tasks import TaskRequest, TaskCreate, TaskResponseStatus, TaskResponse, TaskResponseResult


class TasksRepository():
    @classmethod
    async def create_task(cls, session: AsyncSession, task: TaskCreate) -> TaskResponse | None:
        db_uuid = uuid.uuid4()
        db_time_at = time.time()
        db_task = DevTask(id=db_uuid, created_at=db_time_at,
                             **task.model_dump(include={'device_id', 'method_code'}))  # item.model_dump()
        db_task_payload = DevTaskPayload(task_id=db_uuid, **task.model_dump(mode='json', include={'payload'}))
        db_task_status = DevTaskStatus(task_id=db_uuid, status=TaskStatus.READY,
                                          **task.model_dump(include={'ttl', 'priority'}))
        session.add(db_task)
        session.add(db_task_payload)
        session.add(db_task_status)
        try:
            await session.commit()
        except:
            return None
        return TaskResponse(id=db_task.id)

    @classmethod
    async def get_task(cls, session: AsyncSession, id: TaskRequest) -> TaskResponseResult | None:
        query = (select(DevTask,DevTaskStatus,DevTaskResult)
                 .join(DevTaskStatus)
                 .join(DevTaskResult, isouter=True)
                 .where(DevTask.id == id.id))
        t = await session.execute(query)
        resp = t.first()
        if resp is None:
            return None
        # print(resp[2])
        task: TaskResponseResult = TaskResponseResult(
            id=resp.id
            , method_code=resp.method_code
            , device_id=resp.device_id
            , priority=resp.priority
            , status=resp.status
            , pending_at=resp.pending.at
            , ttl=resp.ttl
            , result = resp.result
        )
        return task

    @classmethod
    async def get_tasks(cls, session: AsyncSession, device_id: int | None = 0) -> Sequence[
        TaskResponseStatus]:
        query = (select(DevTask, DevTaskStatus, DevTaskResult)
                 .join(DevTaskStatus)
                 .where(DevTask.device_id == device_id))
        t = await session.execute(query)
        resp = t.all()

        return resp

    @classmethod
    async def tasks_ttl_update(cls, session: AsyncSession, delta_ttl: int | None = 1):
        await session.execute(update(DevTaskStatus)
                              .where(DevTaskStatus.status < TaskStatus.DONE)
                              .where(DevTaskStatus.ttl > (delta_ttl-1))
                              .values(ttl=DevTaskStatus.ttl - delta_ttl))
        await session.flush()
        await session.commit()
        # except OperationalError as e:
        await session.execute(update(DevTaskStatus)
                              .where(DevTaskStatus.status < TaskStatus.DONE)
                              .where(DevTaskStatus.ttl <= (delta_ttl-1))
                              .values(status=TaskStatus.EXPIRED, ttl=0))
        await session.flush()
        await session.commit()
        return

    @classmethod
    async def task_status_update(cls, session: AsyncSession, task_id: Mapped[uuid.UUID], status:int) -> bool:
        if status in [TaskStatus.PENDING, TaskStatus.LOCK, TaskStatus.DONE]:
            pending_time = time.time()
            qur = (update(DevTaskStatus).where(DevTaskStatus.task_id == task_id)
                   .values(status=status,pending_at=int(pending_time)))
        elif status < TaskStatus.UNDEFINED:
            qur = update(DevTaskStatus).where(DevTaskStatus.task_id == task_id).values(status=status)
        else:
            return False
        await session.execute(qur)
        # except OperationalError as e:
        await session.flush()
        await session.commit()
        return True