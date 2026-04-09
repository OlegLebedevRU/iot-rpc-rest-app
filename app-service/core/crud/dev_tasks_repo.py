import json

from core.logging_config import setup_module_logger
import time
import uuid
from typing import Any

from fastapi_pagination import Page
from fastapi_pagination.ext.sqlalchemy import apaginate
from pydantic import UUID4
from sqlalchemy import (
    select,
    update,
    asc,
    desc,
    func,
    Integer,
    and_,
)
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
    TaskListOut,
)

log = setup_module_logger(__name__, "repo_dev_tasks.log")


class TasksRepository:
    @staticmethod
    def _apply_org_filter(query: Any, org_id: int | None) -> Any:
        """
        Применяет фильтр по организации с безопасным JOIN.
        Использует LEFT JOIN, если org_id не задан, чтобы избежать потери данных.
        """
        if org_id and org_id > 0:
            return (
                query.join(DeviceOrgBind, DevTask.device_id == DeviceOrgBind.device_id)
                .join(
                    Org,
                    and_(DeviceOrgBind.org_id == Org.org_id, Org.is_deleted == False),
                )
                .where(Org.org_id == org_id)
            )
        return query.outerjoin(
            DeviceOrgBind, DevTask.device_id == DeviceOrgBind.device_id
        ).outerjoin(
            Org, and_(DeviceOrgBind.org_id == Org.org_id, Org.is_deleted == False)
        )

    @staticmethod
    def _base_task_query():
        """
        Базовый SELECT с общими полями задачи и статуса.
        """
        return select(
            DevTask.id.label("id"),
            DevTask.ext_task_id.label("ext_task_id"),
            DevTask.method_code.label("method_code"),
            DevTask.device_id.label("device_id"),
            func.extract("EPOCH", DevTask.created_at).cast(Integer).label("created_at"),
            DevTaskStatus.priority.label("priority"),
            DevTaskStatus.status.label("status"),
            func.extract("EPOCH", DevTaskStatus.pending_at)
            .cast(Integer)
            .label("pending_at"),
            func.extract("EPOCH", DevTaskStatus.locked_at)
            .cast(Integer)
            .label("locked_at"),
            DevTaskStatus.ttl.label("ttl"),
            Org.org_id.label("org_id"),
        ).select_from(DevTask)

    @classmethod
    async def create_task(
        cls, session: AsyncSession, task: TaskCreate
    ) -> tuple[UUID4, float] | None:
        db_uuid = uuid.uuid4()
        tsk_q = (
            insert(DevTask)
            .values(
                id=db_uuid,
                ext_task_id=task.ext_task_id,
                created_at=func.current_timestamp(),
                device_id=task.device_id,
                method_code=task.method_code,
            )
            .returning(
                func.extract("EPOCH", DevTask.created_at)
                .cast(Integer)
                .label("created_at")
            )
        )
        payload_q = insert(DevTaskPayload).values(task_id=db_uuid, payload=task.payload)
        status_q = insert(DevTaskStatus).values(
            task_id=db_uuid,
            status=TaskStatus.READY,
            ttl=task.ttl,
            priority=task.priority,
        )

        try:
            result = await session.execute(tsk_q)
            await session.execute(payload_q)
            await session.execute(status_q)
            await session.commit()
            created_at = result.scalar_one()
            log.info("Committed new task %s", db_uuid)
            return db_uuid, created_at
        except Exception as e:
            log.error("Failed to create task %s: %s", db_uuid, e, exc_info=True)
            await session.rollback()
            return None

    @classmethod
    async def get_task(
        cls,
        session: AsyncSession,
        id: UUID4,
        org_id: int,
    ) -> tuple[dict | None, list[dict] | None]:
        query = cls._base_task_query().join(DevTask.status)
        query = cls._apply_org_filter(query, org_id)
        query = query.where(DevTask.id == id, DevTask.is_deleted == False)

        res_q = (
            select(
                DevTaskResult.id.label("id"),
                DevTaskResult.ext_id.label("ext_id"),
                DevTaskResult.status_code.label("status_code"),
                DevTaskResult.result.label("result"),
            )
            .where(DevTaskResult.task_id == id)
            .order_by(DevTaskResult.id.desc())
        )

        t = await session.execute(query)
        resp_task_w_status = t.unique().mappings().one_or_none()

        if resp_task_w_status is None:
            return None, None

        r = await session.execute(res_q)
        # task_results = r.unique().mappings().all()
        task_results = r.mappings().all()
        # Преобразуем RowMapping → dict для совместимости с типами
        result_data = [dict(row) for row in task_results]
        task_data = dict(resp_task_w_status)

        return task_data, result_data

    @classmethod
    def _select_task_query(cls, method_le: int = 65535):
        return (
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
                DevTask.method_code <= method_le,
            )
        )

    @classmethod
    async def select_task_by_id(
        cls,
        session: AsyncSession,
        task_id: UUID4,
        method_le: int = 65535,
    ) -> dict[str, Any] | None:
        query = cls._select_task_query(method_le).where(DevTask.id == task_id)
        result = await session.execute(query)
        row = result.mappings().one_or_none()
        return dict(row) if row is not None else None

    @classmethod
    async def select_next_task_by_sn(
        cls,
        session: AsyncSession,
        sn: str,
        method_le: int = 65535,
    ) -> dict[str, Any] | None:
        subq = (
            select(Device.device_id)
            .where(Device.sn == sn, Device.is_deleted == False)
            .subquery()
        )
        query = (
            cls._select_task_query(method_le)
            .where(DevTask.device_id == subq.c.device_id, DevTaskStatus.ttl > 0)
            .order_by(
                desc(DevTaskStatus.priority),
                asc(DevTaskStatus.ttl),
                asc(DevTask.created_at),
            )
            .limit(1)
        )
        result = await session.execute(query)
        row = result.mappings().one_or_none()
        return dict(row) if row is not None else None

    @classmethod
    async def get_tasks(
        cls,
        session: AsyncSession,
        device_id: int,
        org_id: int,
    ) -> Page[TaskListOut]:
        query = cls._base_task_query()
        query = query.join(DevTask.status)
        query = cls._apply_org_filter(query, org_id)
        query = query.where(DevTask.is_deleted == False)

        if device_id is not None:
            query = query.where(DevTask.device_id == device_id)

        query = query.order_by(DevTask.created_at.desc()).limit(
            settings.db.limit_tasks_result
        )

        return await apaginate(session, query)

    @classmethod
    async def delete_task(
        cls,
        session: AsyncSession,
        id: UUID4,
        org_id: int,
    ) -> TaskResponseDeleted | None:
        exists_q = (
            select(1)
            .join(DeviceOrgBind, DevTask.device_id == DeviceOrgBind.device_id)
            .join(
                Org, and_(DeviceOrgBind.org_id == Org.org_id, Org.is_deleted == False)
            )
            .where(
                DevTask.id == id,
                DevTask.is_deleted == False,
                Org.org_id == org_id,
            )
        )
        exists_result = await session.execute(exists_q)
        if not exists_result.first():
            log.warning("Task %s not found or not accessible for org %s", id, org_id)
            return None

        q1 = (
            update(DevTask)
            .where(DevTask.id == id)
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
        deleted_at = int(resp.deleted_at) if resp else None

        await session.execute(q2)
        try:
            await session.commit()
            log.info("Deleted task %s", id)
        except Exception as e:
            log.error("Failed to delete task %s: %s", id, e)
            await session.rollback()
            return None

        return TaskResponseDeleted(id=id, deleted_at=deleted_at)

    @classmethod
    async def tasks_ttl_update(cls, session: AsyncSession, delta_ttl: int = 1):
        try:
            await session.execute(
                update(DevTaskStatus)
                .where(
                    DevTaskStatus.status < TaskStatus.DONE,
                    DevTaskStatus.ttl > (delta_ttl - 1),
                )
                .values(ttl=DevTaskStatus.ttl - delta_ttl)
            )
            await session.execute(
                update(DevTaskStatus)
                .where(
                    DevTaskStatus.status < TaskStatus.DONE,
                    DevTaskStatus.ttl <= (delta_ttl - 1),
                )
                .values(status=TaskStatus.EXPIRED, ttl=0)
            )
            await session.commit()
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

        try:
            await session.execute(stmt)
            await session.commit()
            log.info("Updated task-status %s to %s", task_id, status)
            return True
        except Exception as e:
            log.error("Failed to update task-status %s: %s", task_id, e)
            await session.rollback()
            return False

    @classmethod
    async def update_ttl(cls, session: AsyncSession, step_ttl: int):
        data = await PersistentVariable.get_data(session, "saved_time_minutes")
        tn = int(time.time()) // 60
        if data and data.var_val.isdigit():
            delta_ttl = tn - int(data.var_val)
            if delta_ttl <= 0:
                delta_ttl = step_ttl
        else:
            delta_ttl = step_ttl

        await cls.tasks_ttl_update(session, delta_ttl)
        await PersistentVariable.upsert_data(
            session, "saved_time_minutes", str(tn), "INT32"
        )

    @classmethod
    async def save_task_result(
        cls,
        session: AsyncSession,
        task_id: UUID4,
        ext_id: int,
        status_code: int,
        result: dict | str,  # Поддержка обоих типов
    ) -> int | None:
        # Verify that the referenced task exists before inserting the result
        task_exists = await session.execute(
            select(DevTask.id).where(DevTask.id == task_id)
        )
        if task_exists.scalar_one_or_none() is None:
            log.warning(
                "Cannot save result: task %s does not exist in the database",
                task_id,
            )
            return None

        # Если result — строка, попробуем распарсить как JSON, иначе обернём
        if isinstance(result, str):
            try:
                parsed_result = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                parsed_result = {"result": result}
        else:
            parsed_result = result

        tsk_q = (
            insert(DevTaskResult)
            .values(
                task_id=task_id,
                ext_id=ext_id,
                status_code=status_code,
                result=parsed_result,  # Теперь передаётся как dict → JSONB
            )
            .returning(DevTaskResult.id)
        )
        try:
            result_row = await session.execute(tsk_q)
            new_id = result_row.scalar_one()
            await session.commit()
            log.info("Task result committed, task_id=%s, result_id=%s", task_id, new_id)
            return new_id
        except Exception as e:
            log.error(
                "Failed to commit task result for task %s: %s",
                task_id,
                e,
                exc_info=True,
            )
            await session.rollback()
            return None
