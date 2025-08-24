import time
import uuid
from typing import List

from pydantic import UUID4
from sqlalchemy import Sequence, Row, select, update, UUID
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import Mapped

from core import settings
from core.models.common import TaskStatus
from core.models.device_tasks import DevTaskStatus, DevTask, DevTaskResult, DevTaskPayload
from core.schemas.device_tasks import TaskRequest, TaskCreate, TaskResponseStatus, TaskResponse, TaskResponseResult, \
    TaskResponseDeleted


class TasksRepository():
    @classmethod
    async def create_task(cls, session: AsyncSession, task: TaskCreate) -> TaskResponse | None:
        db_uuid = uuid.uuid4()
        db_time_at = int(time.time())
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
        return TaskResponse(id=db_task.id, created_at=db_time_at)

    @classmethod
    async def get_task(cls, session: AsyncSession, id: UUID4) -> TaskResponseResult | None:
        query = (select(DevTask.id.label('id'),DevTask.method_code.label('method_code'),
                        DevTask.device_id.label('device_id'),DevTask.created_at.label('created_at'),
                        DevTaskStatus.priority.label('priority'),
                        DevTaskStatus.status.label('status'),DevTaskStatus.pending_at.label('pending_at'),
                        DevTaskStatus.ttl.label('ttl'),
                        DevTaskResult.result.label('result'))
                 .join(DevTaskStatus)
                 .join(DevTaskResult, isouter=True)
                 .where(DevTask.id == id, DevTask.is_deleted==False))
        t = await session.execute(query)
        resp = t.mappings().one_or_none()
        #print(str(resp))
        #print("vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv")
        if resp is None:
            return None
        # print(resp[2])
        task: TaskResponseResult = TaskResponseResult.model_validate(resp)
        return task

    @classmethod
    async def get_tasks(cls, session: AsyncSession, device_id: int | None = 0) -> Sequence[
        TaskResponseStatus]:
        query = (select(DevTask.id.label('id'), DevTask.method_code.label('method_code'),
                        DevTask.device_id.label('device_id'), DevTask.created_at.label('created_at'),
                        DevTaskStatus.priority.label('priority'),
                        DevTaskStatus.status.label('status'), DevTaskStatus.pending_at.label('pending_at'),
                        DevTaskStatus.ttl.label('ttl'))

                 .join(DevTaskStatus)
                 .join(DevTaskResult, isouter=True)
                 .where(DevTask.device_id == device_id, DevTask.is_deleted==False)
                 .limit(settings.db.limit_tasks_result))
        t = await session.execute(query)
        resp = t.mappings().all()

        return resp

    @classmethod
    async def delete_task(cls, session: AsyncSession, id: UUID4) -> TaskResponseDeleted | None:
        db_time_at = int(time.time())
        q1 = update(DevTask).where(DevTask.id == id).values(is_deleted=True, deleted_at=db_time_at)
        q2 = (update(DevTaskStatus).where(DevTaskStatus.task_id == id)
              .values(status=TaskStatus.DELETED))
        await session.execute(q1)
        await session.execute(q2)
        await session.commit()
        return TaskResponseDeleted(id=id, deleted_at=db_time_at)


    @classmethod
    async def tasks_ttl_update(cls, session: AsyncSession, delta_ttl: int | None = 1):
        await session.execute(update(DevTaskStatus)
                              .where(DevTaskStatus.status < TaskStatus.DONE,
                                     DevTaskStatus.ttl > (delta_ttl-1))
                              .values(ttl=DevTaskStatus.ttl - delta_ttl))
        await session.flush()
        await session.commit()
        # except OperationalError as e:
        await session.execute(update(DevTaskStatus)
                              .where(DevTaskStatus.status < TaskStatus.DONE,
                                     DevTaskStatus.ttl <= (delta_ttl-1))
                              .values(status=TaskStatus.EXPIRED, ttl=0))
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
        await session.commit()
        return True