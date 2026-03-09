import logging.handlers
import time
import uuid

from fastapi_pagination import Page
from fastapi_pagination.ext.sqlalchemy import paginate
from pydantic import UUID4
from sqlalchemy import select, update, desc, func, Integer
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio.session import AsyncSession

from core import settings
from core.models import Device, Org
from core.models.common import TaskStatus, PersistentVariable
from core.models.device_tasks import (
    DevTaskStatus,
    DevTask,
    DevTaskResult,
    DevTaskPayload,
)
from core.models.devices import DeviceOrgBind
from core.schemas.device_tasks import (
    TaskCreate,
    TaskResponseDeleted,
    TaskResponsePayload,
    TaskHeader,
    TaskListOut,
)

log = logging.getLogger(__name__)

fh = logging.handlers.RotatingFileHandler(
    "/var/log/app/repo_dev_task.log",
    mode="a",
    maxBytes=10 * 1024 * 1024,
    backupCount=10,
    encoding=None,
)
fh.setLevel(logging.INFO)
formatter = logging.Formatter(settings.logging.log_format)
fh.setFormatter(formatter)


class TasksRepository:
    @classmethod
    async def create_task(cls, session: AsyncSession, task: TaskCreate):
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
        t = await session.execute(tsk_q)
        await session.execute(payload_q)
        await session.execute(status_q)
        try:
            await session.commit()
            created_at = t.one()
            log.info("Committed new task %s", db_uuid)
        except Exception as e:
            log.error("Failed to create task %s: %s", db_uuid, e)
            await session.rollback()
            return None
        return db_uuid, created_at.created_at

    @classmethod
    async def get_task(
        cls,
        session: AsyncSession,
        id: UUID4,
        org_id: int | None = 0,
    ):
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
            # .where(DeviceOrgBind.org_id == org_id)
            .join(Org, DeviceOrgBind.org_id == Org.org_id)
            .where(Org.is_deleted == False)
            .join(DevTask.status)
            .where(DevTask.id == id, DevTask.is_deleted == False)
        )
        if org_id is not None:
            query = query.where(DeviceOrgBind.org_id == org_id)
        res_q = select(
            DevTaskResult.id.label("id"),
            DevTaskResult.ext_id.label("ext_id"),
            DevTaskResult.status_code.label("status_code"),
            DevTaskResult.result.label("result"),
        ).where(DevTaskResult.task_id == id)

        t = await session.execute(query)
        resp_task_w_status = t.unique().mappings().one_or_none()

        if resp_task_w_status is None:
            return None, None
        r = await session.execute(res_q)
        task_results = r.unique().mappings().all()

        return resp_task_w_status, task_results

    @classmethod
    async def select_task(
        cls,
        session: AsyncSession,
        t_req: UUID4 | None = None,  # str = None,
        sn: str = None,
        method_le: int = 65535,
    ) -> TaskResponsePayload | None:
        query = (
            select(
                DevTask.id.label("id"),
                DevTask.ext_task_id.label("ext_task_id"),
                DevTask.method_code.label("method_code"),
                DevTask.device_id.label("device_id"),
                func.extract("EPOCH", DevTask.created_at)
                .cast(Integer)
                .label("created_at"),
                DevTaskStatus.priority.label("priority"),
                DevTaskStatus.status.label("status"),
                func.extract("EPOCH", DevTaskStatus.pending_at)
                .cast(Integer)
                .label("pending_at"),
                func.extract("EPOCH", DevTaskStatus.locked_at)
                .cast(Integer)
                .label("locked_at"),
                DevTaskStatus.ttl.label("ttl"),
                DevTaskPayload.payload.label("payload"),
            )
            .join(DevTaskStatus)
            .join(DevTaskPayload)
            .where(
                DevTask.is_deleted == False,
                DevTaskStatus.status < TaskStatus.DONE,
            )
        )
        if t_req is not None:
            query = query.where(DevTask.id == t_req, DevTask.method_code <= method_le)
        elif sn is not None:
            subq = select(Device).where(Device.sn == sn).subquery()
            query = query.where(
                DevTask.device_id == subq.c.device_id,
                DevTask.method_code <= method_le,
            )
            query = query.order_by(desc(DevTaskStatus.priority), DevTask.created_at)
            query = query.limit(1)
        else:
            return None
        t = await session.execute(query)
        if t is None:
            return None
        resp = t.mappings().one_or_none()
        if resp is None:
            return None
        header: TaskHeader = TaskHeader.model_validate(resp)
        task: TaskResponsePayload = TaskResponsePayload(
            header=header,
            id=resp.id,
            status=resp.status,
            created_at=resp.created_at,
            pending_at=resp.pending_at if resp.pending_at is not None else None,
            locked_at=resp.locked_at if resp.locked_at is not None else None,
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
        query = select(
            DevTask.id.label("id"),
            DevTask.ext_task_id.label("ext_task_id"),
            DevTask.method_code.label("method_code"),
            DevTask.device_id.label("device_id"),
            DevTaskStatus.priority.label("priority"),
            DevTaskStatus.ttl.label("ttl"),
            DevTaskStatus.status.label("status"),
            func.extract("EPOCH", DevTask.created_at).label("created_at"),
            func.extract("EPOCH", DevTaskStatus.pending_at).label("pending_at"),
            func.extract("EPOCH", DevTaskStatus.locked_at).label("locked_at"),
            Org.org_id.label("org_id"),
        ).select_from(DevTask)

        # Всегда джойним статус
        query = query.join(DevTask.status)

        # Если задан org_id — обязательно джойним DeviceOrgBind и Org
        if org_id and org_id > 0:
            query = (
                query.join(DeviceOrgBind, DevTask.device_id == DeviceOrgBind.device_id)
                .join(Org, DeviceOrgBind.org_id == Org.org_id)
                .where(
                    Org.org_id == org_id,
                    Org.is_deleted == False,
                )
            )
        else:
            # Если org_id не задан или 0 — можно либо не фильтровать по Org,
            # либо оставить только DevTask (без привязки к организации)
            # Но тогда Org.org_id будет NULL — будьте осторожны в схеме
            pass

        # Общие условия
        query = query.where(
            DevTask.is_deleted == False,
        )

        if device_id:
            query = query.where(DevTask.device_id == device_id)

        query = query.order_by(DevTask.created_at.desc()).limit(
            settings.db.limit_tasks_result
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
                DevTask.id == id,
                DevTask.is_deleted == False,
                DevTask.device_id.in_(
                    select(DeviceOrgBind.device_id)
                    .join(Org, DeviceOrgBind.org_id == Org.org_id)
                    .where(
                        DeviceOrgBind.org_id == org_id,
                        Org.is_deleted == False,
                    )
                ),
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
        log.info("deleted task %s", str(id))

        return TaskResponseDeleted(
            id=id,
            deleted_at=deleted_at if deleted_at is not None else None,
        )

    @classmethod
    async def tasks_ttl_update(cls, session: AsyncSession, delta_ttl: int = 1):
        # Уменьшаем TTL
        try:
            await session.execute(
                update(DevTaskStatus)
                .where(
                    DevTaskStatus.status < TaskStatus.DONE,
                    DevTaskStatus.ttl > (delta_ttl - 1),
                )
                .values(ttl=DevTaskStatus.ttl - delta_ttl)
            )
            # Помечаем как EXPIRED
            await session.execute(
                update(DevTaskStatus)
                .where(
                    DevTaskStatus.status < TaskStatus.DONE,
                    DevTaskStatus.ttl <= (delta_ttl - 1),
                )
                .values(status=TaskStatus.EXPIRED, ttl=0)
            )
            await session.commit()  # Один коммит на всю операцию
        except Exception as e:
            await session.rollback()
            log.error("Failed to update TTLs: %s", e)
            raise

    @classmethod
    async def task_status_update(
        cls, session: AsyncSession, task_id: UUID4 | None, status: int
    ) -> bool:
        if task_id is None:
            return True
        stmt = update(DevTaskStatus).where(DevTaskStatus.task_id == task_id)
        match status:
            case TaskStatus.PENDING | TaskStatus.DONE:
                stmt = stmt.values(status=status, pending_at=func.current_timestamp())
            case TaskStatus.LOCK:
                stmt = stmt.values(
                    status=TaskStatus.LOCK, locked_at=func.current_timestamp()
                )
            case TaskStatus.DELETED:
                stmt = stmt.where(DevTaskStatus.status < TaskStatus.DONE).values(
                    status=status
                )
            case status if status < TaskStatus.UNDEFINED:
                stmt = stmt.values(status=status)
            case _:
                return False
        await session.execute(stmt)
        try:
            await session.commit()
            log.info("Updated task-status %s", str(task_id))
        except Exception as e:
            log.error("Failed to update task-status %s: %s", str(task_id), e)
            await session.rollback()
            return False
        return True

    @classmethod
    async def update_ttl(cls, session: AsyncSession, step_ttl: int):
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
            .returning(DevTaskResult.id)
        )
        result = await session.execute(tsk_q)
        new_id = result.scalar_one()

        try:
            await session.commit()
            log.info("Task result committed, task_id=%s, result_id=%s", task_id, new_id)
        except Exception as e:
            log.error("Failed to commit task result for task %s: %s", task_id, e)
            await session.rollback()
            return None
        return new_id
