import logging
import time
import uuid
from typing import List

from pydantic import UUID4
from sqlalchemy import Sequence, Row, select, update, UUID, desc, RowMapping, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import Mapped, aliased

from core import settings
from core.models import db_helper, Device
from core.models.common import TaskStatus, PersistentVariable
from core.models.device_tasks import DevTaskStatus, DevTask, DevTaskResult, DevTaskPayload
from core.schemas.device_tasks import TaskRequest, TaskCreate, TaskResponseStatus, TaskResponse, TaskResponseResult, \
    TaskResponseDeleted, TaskResponsePayload, TaskHeader


class TasksRepository():
    @classmethod
    async def create_task(cls, session: AsyncSession, task: TaskCreate) -> TaskResponse | None:
        db_uuid = uuid.uuid4()
        #db_time_at = int(time.time())
        tsk_q = (insert(DevTask).values(id=db_uuid, created_at=func.now(),
                                       device_id = task.device_id, method_code = task.method_code)
                 .returning(DevTask.created_at))
        payload_q = insert(DevTaskPayload).values(task_id=db_uuid,payload=task.payload)
        status_q = insert(DevTaskStatus).values(task_id=db_uuid, status=TaskStatus.READY,
                                                ttl=task.ttl, priority=task.priority)
        # db_task = DevTask(id=db_uuid, created_at=func.current_datetime(),
        #                      **task.model_dump(include={'device_id', 'method_code'}))  # item.model_dump()
        # db_task_payload = DevTaskPayload(task_id=db_uuid, **task.model_dump(mode='json', include={'payload'}))
        # db_task_status = DevTaskStatus(task_id=db_uuid, status=TaskStatus.READY,
        #                                   **task.model_dump(include={'ttl', 'priority'}))
        t = await session.execute(tsk_q)
        await session.execute(payload_q)
        await session.execute(status_q)
        # session.add(db_task_payload)
        # session.add(db_task_status)
        try:
            await session.commit()
            created_at = t.one()
            logging.info(f"commited new task {db_uuid}")
        except:
            return None
        return TaskResponse(id=db_uuid, created_at=created_at.created_at)

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
        header: TaskHeader = TaskHeader.model_validate(resp)
        task: TaskResponseResult = TaskResponseResult(header=header,
                                                      id=resp.id,
                                                      status=resp.status,
                                                      created_at=resp.created_at,
                                                      pending_at=resp.pending_at,
                                                      result=resp.result
                                                      )
        return task

    @classmethod
    async def select_task(cls, session: AsyncSession, t_req: TaskRequest = None, sn : str = None) -> TaskResponsePayload | None:
        if t_req is not None:
            query = (select(DevTask.id.label('id'),DevTask.method_code.label('method_code'),
                            DevTask.device_id.label('device_id'),DevTask.created_at.label('created_at'),
                            DevTaskStatus.priority.label('priority'),
                            DevTaskStatus.status.label('status'),DevTaskStatus.pending_at.label('pending_at'),
                            DevTaskStatus.ttl.label('ttl'),
                            DevTaskPayload.payload.label('payload'))
                     .join(DevTaskStatus)
                     .join(DevTaskPayload)
                     .where(DevTask.id == t_req,
                            DevTask.is_deleted==False,
                            DevTaskStatus.status <TaskStatus.DONE))
        else:
            subq = select(Device).where( Device.sn==sn).subquery()
            query = (select(DevTask.id.label('id'),DevTask.method_code.label('method_code'),
                            DevTask.device_id.label('device_id'),DevTask.created_at.label('created_at'),
                            DevTaskStatus.priority.label('priority'),
                            DevTaskStatus.status.label('status'),DevTaskStatus.pending_at.label('pending_at'),
                            DevTaskStatus.ttl.label('ttl'),
                            DevTaskPayload.payload.label('payload'))
                     .join(DevTaskStatus).join(DevTaskPayload)
                     .where(DevTask.device_id == subq.c.device_id,
                            DevTask.is_deleted==False,DevTaskStatus.status <TaskStatus.LOCK)
                     .order_by(desc(DevTaskStatus.priority), DevTask.created_at)
                     .limit(1))

        t = await session.execute(query)
        if t is None:
            return None
        resp = t.mappings().one_or_none()
        #print(str(resp))
        #print("vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv")
        if resp is None:
            return None
        # print(resp[2])
        header: TaskHeader = TaskHeader.model_validate(resp)
        task: TaskResponsePayload = TaskResponsePayload(header=header,
                                                        id=resp.id,
                                                        status=resp.status,
                                                        created_at=resp.created_at,
                                                        pending_at=resp.pending_at,
                                                        payload=resp.payload)
        return task

    @classmethod
    async def get_tasks(cls, session: AsyncSession, device_id: int | None = 0) -> Sequence[
        RowMapping]:
        a_dts: DevTaskStatus = aliased(DevTaskStatus)
        subq = (select(DevTask.id.label('id'),DevTask.method_code.label('method_code'),
                        DevTask.device_id.label('device_id'),
                        DevTaskStatus.priority.label('priority'),DevTaskStatus.ttl.label('ttl'))
                .join(DevTaskStatus, DevTask.id==DevTaskStatus.task_id)
                .where(DevTask.device_id == device_id, DevTask.is_deleted==False).subquery())
        query = (select(DevTask.id.label('id'),DevTask.method_code.label('method_code'),
                        DevTask.device_id.label('device_id'),
                        DevTaskStatus.priority.label('priority'),DevTaskStatus.ttl.label('ttl'),
                        DevTaskStatus.status.label('status'), DevTask.created_at.label('created_at'),
                        DevTaskStatus.pending_at.label('pending_at'),DevTaskStatus.locked_at.label('locked_at'))
                 #.join(subq)


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
              .values(status=TaskStatus.DELETED, ttl=0))
        await session.execute(q1)
        await session.execute(q2)
        await session.commit()
        logging.info(f"deleted task {id}")
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
                              .where(
                                     DevTaskStatus.status < TaskStatus.DONE,
                                     DevTaskStatus.ttl <= (delta_ttl-1))
                              .values(status=TaskStatus.EXPIRED, ttl=0))
        await session.commit()
        return

    @classmethod
    async def task_status_update(cls, session: AsyncSession, task_id: Mapped[uuid.UUID] | None, status:int) -> bool:
        if task_id is None:
            return True
        if status in [TaskStatus.PENDING, TaskStatus.LOCK, TaskStatus.DONE]:
            pending_time = time.time()
            qur = (update(DevTaskStatus).where(DevTaskStatus.task_id == task_id)
                   .values(status=status,pending_at=func.current_timestamp()))
        elif status == TaskStatus.DELETED:
            qur = update(DevTaskStatus).where(DevTaskStatus.task_id == task_id,
                                              DevTaskStatus.status < TaskStatus.DONE).values(status=status)
        elif status < TaskStatus.UNDEFINED:
            qur = update(DevTaskStatus).where(DevTaskStatus.task_id == task_id).values(status=status)
        else:
            return False
        await session.execute(qur)
        # except OperationalError as e:
        await session.commit()
        return True
    @classmethod
    async def update_ttl(cls, session: AsyncSession, step_ttl:int):
        # session = await anext(db_helper.session_getter())
        # async with db_helper.session_getter() as session:
        # saved_min = await PersistentVariables.get_data(session, "saved_time_minutes")
        data = await PersistentVariable.get_data(session, "saved_time_minutes")
        tn = int(time.time()) // 60
        if data is not None:
            if data.var_val.isdigit():
                delta_ttl = tn - int(data.var_val)
                if delta_ttl <= 0:
                    delta_ttl = step_ttl
            else:
                delta_ttl = step_ttl
        else:
            delta_ttl = step_ttl
        await TasksRepository.tasks_ttl_update(session, delta_ttl)
        await PersistentVariable.upsert_data(session, "saved_time_minutes", str(tn), "INT32")
        return