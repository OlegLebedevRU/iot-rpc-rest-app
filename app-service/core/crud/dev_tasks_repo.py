import logging
import time
import uuid
from fastapi_pagination import Page
from fastapi_pagination.ext.sqlalchemy import paginate
from pydantic import UUID4
from sqlalchemy import select, update, desc, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import Mapped
from core import settings
from core.models import Device
from core.models.common import TaskStatus, PersistentVariable
from core.models.device_tasks import (
    DevTaskStatus,
    DevTask,
    DevTaskResult,
    DevTaskPayload,
)
from core.models.devices import DeviceOrgBind
from core.models.orgs import Org
from core.schemas.device_tasks import (
    TaskCreate,
    TaskResponse,
    TaskResponseResult,
    TaskResponseDeleted,
    TaskResponsePayload,
    TaskHeader,
    ResultArray,
    TaskListOut,
)


class TasksRepository:
    @classmethod
    async def create_task(
        cls, session: AsyncSession, task: TaskCreate
    ) -> TaskResponse | None:
        db_uuid = uuid.uuid4()
        # db_time_at = int(time.time())
        tsk_q = (
            insert(DevTask)
            .values(
                id=db_uuid,
                ext_task_id=task.ext_task_id,
                created_at=func.current_timestamp(),
                device_id=task.device_id,
                method_code=task.method_code,
            )
            .returning(func.extract("EPOCH", DevTask.created_at).label("created_at"))
        )
        payload_q = insert(DevTaskPayload).values(task_id=db_uuid, payload=task.payload)
        status_q = insert(DevTaskStatus).values(
            task_id=db_uuid,
            status=TaskStatus.READY,
            ttl=task.ttl,
            priority=task.priority,
        )
        # db_task = DevTask(id=db_uuid, created_at=func.current_datetime(),
        #                      **task.model_dump(include={'device_id', 'method_code'}))  # item.model_dump()
        # db_task_payload = DevTaskPayload(task_id=db_uuid, **task.model_dump(mode='json', include={'payload'}))
        # db_task_status = DevTaskStatus(task_id=db_uuid, status=TaskStatus.READY,
        #                                   **task.model_dump(include={'ttl', 'priority'}))
        t = await session.execute(tsk_q)
        await session.execute(payload_q)
        await session.execute(status_q)
        try:
            await session.commit()
            created_at = t.one()
            logging.info(f"commited new task {db_uuid}")
        except:
            return None
        return TaskResponse(id=db_uuid, created_at=int(created_at.created_at))

    @classmethod
    async def get_task(
        cls,
        session: AsyncSession,
        id: UUID4,
        org_id: int | None = 0,
    ) -> TaskResponseResult | None:
        query = (
            select(
                DevTask.id.label("id"),
                DevTask.ext_task_id.label("ext_task_id"),
                DevTask.method_code.label("method_code"),
                DevTask.device_id.label("device_id"),
                func.extract("EPOCH", DevTask.created_at).label("created_at"),
                DevTaskStatus.priority.label("priority"),
                DevTaskStatus.status.label("status"),
                func.extract("EPOCH", DevTaskStatus.pending_at).label("pending_at"),
                func.extract("EPOCH", DevTaskStatus.locked_at).label("locked_at"),
                DevTaskStatus.ttl.label("ttl"),
                Org,
                DeviceOrgBind,
            )
            .join(DeviceOrgBind, DevTask.device_id == DeviceOrgBind.device_id)
            .where(DeviceOrgBind.org_id == org_id)
            .join(Org, DeviceOrgBind.org_id == Org.org_id)
            .where(Org.is_deleted == False)
            .join(DevTaskStatus)
            .where(DevTask.id == id, DevTask.is_deleted == False)
        )
        res_q = select(
            DevTaskResult.id.label("id"),
            DevTaskResult.ext_id.label("ext_id"),
            DevTaskResult.status_code.label("status_code"),
            DevTaskResult.result.label("result"),
        ).where(DevTaskResult.task_id == id)

        t = await session.execute(query)
        resp = t.mappings().one_or_none()

        # print(str(resp))
        # print("vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv")
        if resp is None:
            return None
        r = await session.execute(res_q)
        res = r.mappings().all()
        results = []
        header: TaskHeader = TaskHeader.model_validate(resp)
        for r in res:
            results.append(ResultArray.model_validate(r))
        # results: ResultArray = ResultArray(res)
        task: TaskResponseResult = TaskResponseResult(
            header=header,
            id=resp.id,
            status=resp.status,
            created_at=int(resp.created_at),
            pending_at=int(resp.pending_at) if resp.pending_at is not None else None,
            locked_at=int(resp.locked_at) if resp.locked_at is not None else None,
            results=results,
        )
        return task

    @classmethod
    async def select_task(
        cls, session: AsyncSession, t_req: str = None, sn: str = None
    ) -> TaskResponsePayload | None:
        if t_req is not None and t_req != uuid.UUID(int=0):
            query = (
                select(
                    DevTask.id.label("id"),
                    DevTask.ext_task_id.label("ext_task_id"),
                    DevTask.method_code.label("method_code"),
                    DevTask.device_id.label("device_id"),
                    func.extract("EPOCH", DevTask.created_at).label("created_at"),
                    DevTaskStatus.priority.label("priority"),
                    DevTaskStatus.status.label("status"),
                    func.extract("EPOCH", DevTaskStatus.pending_at).label("pending_at"),
                    func.extract("EPOCH", DevTaskStatus.locked_at).label("locked_at"),
                    DevTaskStatus.ttl.label("ttl"),
                    DevTaskPayload.payload.label("payload"),
                )
                .join(DevTaskStatus)
                .join(DevTaskPayload)
                .where(
                    DevTask.id == t_req,
                    DevTask.is_deleted == False,
                    DevTaskStatus.status < TaskStatus.DONE,
                )
            )
        else:
            subq = select(Device).where(Device.sn == sn).subquery()
            query = (
                select(
                    DevTask.id.label("id"),
                    DevTask.ext_task_id.label("ext_task_id"),
                    DevTask.method_code.label("method_code"),
                    DevTask.device_id.label("device_id"),
                    func.extract("EPOCH", DevTask.created_at).label("created_at"),
                    DevTaskStatus.priority.label("priority"),
                    DevTaskStatus.status.label("status"),
                    func.extract("EPOCH", DevTaskStatus.pending_at).label("pending_at"),
                    func.extract("EPOCH", DevTaskStatus.locked_at).label("locked_at"),
                    DevTaskStatus.ttl.label("ttl"),
                    DevTaskPayload.payload.label("payload"),
                )
                .join(DevTaskStatus)
                .join(DevTaskPayload)
                .where(
                    DevTask.device_id == subq.c.device_id,
                    DevTask.is_deleted == False,
                    DevTaskStatus.status < TaskStatus.LOCK,
                )
                .order_by(desc(DevTaskStatus.priority), DevTask.created_at)
                .limit(1)
            )

        t = await session.execute(query)
        if t is None:
            return None
        resp = t.mappings().one_or_none()
        # print(str(resp))
        # print("vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv")
        if resp is None:
            return None
        # print(resp[2])
        header: TaskHeader = TaskHeader.model_validate(resp)
        task: TaskResponsePayload = TaskResponsePayload(
            header=header,
            id=resp.id,
            status=resp.status,
            created_at=int(resp.created_at),
            pending_at=int(resp.pending_at) if resp.pending_at is not None else None,
            locked_at=int(resp.locked_at) if resp.locked_at is not None else None,
            payload=resp.payload,
        )
        return task

    @classmethod
    async def get_tasks(
        cls,
        session: AsyncSession,
        device_id: int | None = 0,
        org_id: int | None = 0,
    ) -> Page[TaskListOut]:
        query = (
            select(
                DevTask.id.label("id"),
                DevTask.ext_task_id.label("ext_task_id"),
                DevTask.method_code.label("method_code"),
                DevTask.device_id.label("device_id"),
                DevTaskStatus.priority.label("priority"),
                DevTaskStatus.ttl.label("ttl"),
                DevTaskStatus.status.label("status"),
                DevTask.created_at.label("created_at"),
                DevTaskStatus.pending_at.label("pending_at"),
                DevTaskStatus.locked_at.label("locked_at"),
                Org,
                DeviceOrgBind,
            )
            .join(DeviceOrgBind, DevTask.device_id == DeviceOrgBind.device_id)
            .where(DeviceOrgBind.org_id == org_id)
            .join(Org, DeviceOrgBind.org_id == Org.org_id)
            .where(Org.is_deleted == False)
            .join(DevTaskStatus)
            .join(DevTaskResult, isouter=True)
            .where(DevTask.device_id == device_id, DevTask.is_deleted == False)
            .order_by(DevTask.created_at.desc())
            .limit(settings.db.limit_tasks_result)
        )
        return await paginate(session, query)

    @classmethod
    async def delete_task(
        cls,
        session: AsyncSession,
        id: UUID4,
        org_id: int | None = 0,
    ) -> TaskResponseDeleted | None:
        # db_time_at = int(time.time())
        q1 = (
            update(DevTask)
            .where(
                DevTask.id
                == select(DevTask.id)
                .join(DeviceOrgBind, DevTask.device_id == DeviceOrgBind.device_id)
                .where(DeviceOrgBind.org_id == org_id)
                .join(Org, DeviceOrgBind.org_id == Org.org_id)
                .where(Org.is_deleted == False)
                .where(DevTask.id == id)
                .where(DevTask.is_deleted == False)
            )
            .values(is_deleted=True, deleted_at=func.current_timestamp())
            .returning(func.extract("EPOCH", DevTask.deleted_at).label("deleted_at"))
        )
        q2 = (
            update(DevTaskStatus)
            .where(DevTaskStatus.task_id == id)
            .values(status=TaskStatus.DELETED, ttl=0)
        )
        d = await session.execute(q1)
        resp = d.one_or_none()
        if resp:
            await session.execute(q2)
            deleted_at = int(resp.deleted_at) if resp.deleted_at is not None else None
        else:
            deleted_at = None
        await session.commit()
        logging.info("deleted task %s", str(id))

        return TaskResponseDeleted(
            id=id,
            deleted_at=deleted_at if deleted_at is not None else None,
        )

    @classmethod
    async def tasks_ttl_update(cls, session: AsyncSession, delta_ttl: int | None = 1):

        await session.execute(
            update(DevTaskStatus)
            .where(
                DevTaskStatus.status < TaskStatus.DONE,
                DevTaskStatus.ttl > (delta_ttl - 1),
            )
            .values(ttl=DevTaskStatus.ttl - delta_ttl)
        )
        await session.flush()
        await session.commit()
        # except OperationalError as e:
        await session.execute(
            update(DevTaskStatus)
            .where(
                DevTaskStatus.status < TaskStatus.DONE,
                DevTaskStatus.ttl <= (delta_ttl - 1),
            )
            .values(status=TaskStatus.EXPIRED, ttl=0)
        )
        await session.commit()
        return

    @classmethod
    async def task_status_update(
        cls, session: AsyncSession, task_id: Mapped[uuid.UUID] | None, status: int
    ) -> bool:
        if task_id is None:
            return True
        if status in [TaskStatus.PENDING, TaskStatus.DONE]:

            qur = (
                update(DevTaskStatus)
                .where(DevTaskStatus.task_id == task_id)
                .values(status=status, pending_at=func.current_timestamp())
            )
        elif status == TaskStatus.LOCK:

            qur = (
                update(DevTaskStatus)
                .where(DevTaskStatus.task_id == task_id)
                .values(status=TaskStatus.LOCK, locked_at=func.current_timestamp())
            )
        elif status == TaskStatus.DELETED:
            qur = (
                update(DevTaskStatus)
                .where(
                    DevTaskStatus.task_id == task_id,
                    DevTaskStatus.status < TaskStatus.DONE,
                )
                .values(status=status)
            )
        elif status < TaskStatus.UNDEFINED:
            qur = (
                update(DevTaskStatus)
                .where(DevTaskStatus.task_id == task_id)
                .values(status=status)
            )
        else:
            return False
        await session.execute(qur)
        # except OperationalError as e:
        await session.commit()
        return True

    @classmethod
    async def update_ttl(cls, session: AsyncSession, step_ttl: int):
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
        await PersistentVariable.upsert_data(
            session, "saved_time_minutes", str(tn), "INT32"
        )
        return

    @classmethod
    async def save_task_result(
        cls,
        session: AsyncSession,
        task_id: UUID4,
        ext_id: int,
        status_code: int,
        result: str,
    ) -> int | None:
        tsk_q = (
            insert(DevTaskResult)
            .values(
                task_id=task_id,
                ext_id=ext_id,
                status_code=status_code,
                result=result,
            )
            .returning(DevTaskResult.id.label("id"))
        )
        t = await session.execute(tsk_q)

        try:
            await session.commit()
            id_new = t.one()
            logging.info("commited new result %s", task_id)
        except:
            return None
        return id_new.id
