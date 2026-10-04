import json
import hashlib
from math import ceil
from datetime import datetime, timedelta
from dataclasses import dataclass

from core.logging_config import setup_module_logger
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
    case,
    exists,
    literal,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy.engine import CursorResult
from typing import cast

from core import settings
from core.models import Device, Org
from core.models.common import TaskStatus
from core.models.device_tasks import (
    DevTaskStatus,
    DevTask,
    DevTaskResult,
    DevTaskPayload,
    RpcResultWebhook,
)
from core.models.webhook import OrgWebhook
from core.models.devices import DeviceOrgBind
from core.schemas.device_tasks import (
    TaskCreate,
    TaskResponseDeleted,
    TaskListOut,
)

log = setup_module_logger(__name__, "repo_dev_tasks.log")


@dataclass(frozen=True)
class StoredTaskResult:
    result_id: int
    ext_id: int
    status_code: int
    result: dict[str, Any]
    is_new: bool
    send_webhook: bool


class TasksRepository:
    @staticmethod
    def _remaining_ttl():
        return case(
            (DevTaskStatus.initial_ttl == 0, literal(0)),
            else_=func.greatest(
                0,
                func.ceil(
                    func.extract(
                        "epoch", DevTaskStatus.expires_at - func.clock_timestamp()
                    )
                    / 60
                ),
            ),
        ).cast(Integer)

    @staticmethod
    def result_fingerprint(ext_id: int, status_code: int, result: dict) -> str:
        canonical = json.dumps(
            [ext_id, status_code, result],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_result_for_storage(result: Any) -> dict[str, Any]:
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError, TypeError:
                return {"value": result}

        if isinstance(result, dict):
            return result

        return {"value": result}

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
                    and_(DeviceOrgBind.org_id == Org.org_id, Org.is_deleted.is_(False)),
                )
                .where(Org.org_id == org_id)
            )
        return query.outerjoin(
            DeviceOrgBind, DevTask.device_id == DeviceOrgBind.device_id
        ).outerjoin(
            Org, and_(DeviceOrgBind.org_id == Org.org_id, Org.is_deleted.is_(False))
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
            case(
                (
                    DevTaskStatus.status < TaskStatus.DONE,
                    TasksRepository._remaining_ttl(),
                ),
                else_=DevTaskStatus.ttl,
            ).label("ttl"),
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
        deadline = select(DevTask.created_at).where(
            DevTask.id == db_uuid
        ).scalar_subquery() + timedelta(minutes=task.ttl or 1)
        if task.method_code == 7011:
            assert task.payload is not None
            deadline = func.least(
                deadline, func.to_timestamp(task.payload["dt"][0]["pin_expires_at"])
            )
        status_q = insert(DevTaskStatus).values(
            task_id=db_uuid,
            status=TaskStatus.READY,
            ttl=task.ttl,
            initial_ttl=task.ttl,
            expires_at=deadline,
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
            log.error("Failed to create task %s: %s", db_uuid, type(e).__name__)
            await session.rollback()
            return None

    @classmethod
    async def get_task(
        cls,
        session: AsyncSession,
        id: UUID4,
        org_id: int,
    ) -> tuple[dict | None, list[dict] | None]:
        query = (
            cls._base_task_query()
            .join(DevTask.status)
            .outerjoin(DevTaskPayload)
            .add_columns(DevTaskPayload.payload.label("payload"))
        )
        query = cls._apply_org_filter(query, org_id)
        query = query.where(DevTask.id == id, DevTask.is_deleted.is_(False))

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
        # Organization joins can repeat the same task. JSONB payload is not
        # hashable, so deduplicate by the task identity, never by the whole row.
        resp_task_w_status = t.unique(lambda row: row.id).mappings().one_or_none()

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
                cls._remaining_ttl().label("ttl"),
                DevTaskPayload.payload.label("payload"),
                DevTaskStatus.expires_at.label("expires_at"),
            )
            .join(DevTaskStatus)
            .join(DevTaskPayload)
            .where(
                DevTask.is_deleted.is_(False),
                DevTaskStatus.status < TaskStatus.DONE,
                DevTaskStatus.expires_at > func.clock_timestamp(),
                DevTask.method_code <= method_le,
            )
        )

    @classmethod
    async def select_task_by_id(
        cls,
        session: AsyncSession,
        task_id: UUID4,
        method_le: int = 65535,
        sn: str | None = None,
    ) -> dict[str, Any] | None:
        query = cls._select_task_query(method_le).where(DevTask.id == task_id)
        if sn is not None:
            query = query.join(Device, DevTask.device_id == Device.device_id).where(
                Device.sn == sn, Device.is_deleted.is_(False)
            )
        result = await session.execute(query)
        row = result.mappings().one_or_none()
        return dict(row) if row is not None else None

    @classmethod
    async def select_next_task_by_sn(
        cls,
        session: AsyncSession,
        sn: str,
        method_le: int = 65535,
        method_codes: set[int] | None = None,
    ) -> dict[str, Any] | None:
        subq = (
            select(Device.device_id)
            .where(Device.sn == sn, Device.is_deleted.is_(False))
            .subquery()
        )
        query = (
            cls._select_task_query(method_le)
            .where(
                DevTask.device_id == subq.c.device_id,
                DevTaskStatus.initial_ttl > 0,
            )
            .order_by(
                desc(DevTaskStatus.priority),
                asc(cls._remaining_ttl()),
                asc(DevTask.created_at),
            )
            .limit(1)
        )
        if method_codes is not None:
            query = query.where(DevTask.method_code.in_(sorted(method_codes)))
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
        query = query.where(DevTask.is_deleted.is_(False))

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
            .select_from(DevTask)
            .join(DeviceOrgBind, DevTask.device_id == DeviceOrgBind.device_id)
            .join(
                Org, and_(DeviceOrgBind.org_id == Org.org_id, Org.is_deleted.is_(False))
            )
            .where(
                DevTask.id == id,
                DevTask.is_deleted.is_(False),
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
        await cls.scrub_renewal_payload(session, [id])
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
        expired = await session.execute(
            update(DevTaskStatus)
            .where(
                DevTaskStatus.status < TaskStatus.DONE,
                DevTaskStatus.expires_at <= func.clock_timestamp(),
            )
            .values(status=TaskStatus.EXPIRED, ttl=0)
            .returning(DevTaskStatus.task_id)
        )
        ids = list(expired.scalars().all())
        if ids:
            await cls.scrub_renewal_payload(session, ids)
        await session.commit()

    @staticmethod
    async def scrub_renewal_payload(
        session: AsyncSession, ids: list[uuid.UUID]
    ) -> None:
        await session.execute(
            update(DevTaskPayload)
            .where(
                DevTaskPayload.task_id.in_(ids),
                exists(
                    select(1).where(
                        DevTask.id == DevTaskPayload.task_id,
                        DevTask.method_code == 7011,
                    )
                ),
            )
            .values(payload={"dt": []})
        )

    @classmethod
    async def task_status_update(
        cls,
        session: AsyncSession,
        task_id: UUID4 | None,
        status: int,
        sn: str | None = None,
    ) -> bool:
        if task_id is None:
            return True

        if task_id == settings.task_proc_cfg.zero_corr_id:
            log.debug("Skip task-status update for polling corr_id=%s", task_id)
            return True

        stmt = update(DevTaskStatus).where(DevTaskStatus.task_id == task_id)
        if sn is not None:
            stmt = stmt.where(
                exists(
                    select(1)
                    .select_from(DevTask)
                    .join(Device, DevTask.device_id == Device.device_id)
                    .where(
                        DevTask.id == task_id,
                        DevTask.is_deleted.is_(False),
                        Device.sn == sn,
                        Device.is_deleted.is_(False),
                    )
                )
            )
        match status:
            case TaskStatus.PENDING:
                stmt = stmt.where(
                    DevTaskStatus.status == TaskStatus.READY,
                    DevTaskStatus.expires_at > func.clock_timestamp(),
                ).values(status=status, pending_at=func.clock_timestamp())
            case TaskStatus.LOCK:
                stmt = stmt.where(
                    DevTaskStatus.status < TaskStatus.DONE,
                    DevTaskStatus.expires_at > func.clock_timestamp(),
                ).values(status=TaskStatus.LOCK, locked_at=func.clock_timestamp())
            case TaskStatus.DONE:
                stmt = stmt.where(DevTaskStatus.status < TaskStatus.DONE).values(
                    status=status
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
            if sn is not None:
                owner = await session.execute(
                    select(DevTask.id)
                    .join(Device, Device.device_id == DevTask.device_id)
                    .where(
                        DevTask.id == task_id,
                        DevTask.is_deleted.is_(False),
                        Device.sn == sn,
                        Device.is_deleted.is_(False),
                    )
                    .with_for_update(of=DevTask)
                )
                if owner.scalar_one_or_none() is None:
                    await session.rollback()
                    return False
            result = await session.execute(stmt)
            await session.commit()
            return bool(cast(CursorResult, result).rowcount)
        except Exception as e:
            log.error("Failed to update task-status %s: %s", task_id, e)
            await session.rollback()
            return False

    @classmethod
    async def update_ttl(cls, session: AsyncSession, step_ttl: int):
        await cls.tasks_ttl_update(session)

    @classmethod
    async def record_result(
        cls,
        session: AsyncSession,
        task_id: UUID4,
        sn: str,
        ext_id: int,
        status_code: int,
        result: Any,
        result_uid: uuid.UUID | None,
        received_at: datetime,
    ) -> StoredTaskResult | None:
        """Serialize all results of one task on its status row, then commit once."""
        # Match DELETE's lock order: task first, status second.
        owner_row = await session.execute(
            select(DevTask.id, DevTask.is_deleted, DevTask.method_code)
            .join(Device, Device.device_id == DevTask.device_id)
            .where(
                DevTask.id == task_id,
                Device.sn == sn,
                Device.is_deleted.is_(False),
            )
            .with_for_update(of=DevTask)
        )
        owner = owner_row.one_or_none()
        if owner is None:
            await session.rollback()
            return None
        task_row = await session.execute(
            select(DevTaskStatus)
            .where(DevTaskStatus.task_id == task_id)
            .with_for_update(of=DevTaskStatus)
        )
        task_status = task_row.scalar_one_or_none()
        if task_status is None:
            await session.rollback()
            return None
        is_deleted = owner.is_deleted
        parsed = cls._normalize_result_for_storage(result)
        fingerprint = (
            None
            if result_uid is not None
            else cls.result_fingerprint(ext_id, status_code, parsed)
        )
        existing_query = select(DevTaskResult).where(DevTaskResult.task_id == task_id)
        if result_uid is not None:
            existing_query = existing_query.where(
                DevTaskResult.result_uid == result_uid
            )
        else:
            existing_query = existing_query.where(
                DevTaskResult.result_uid.is_(None),
                DevTaskResult.ext_id == ext_id,
                DevTaskResult.status_code == status_code,
                DevTaskResult.result == parsed,
            )
        existing = (
            await session.execute(existing_query.order_by(DevTaskResult.id).limit(1))
        ).scalar_one_or_none()
        if existing is not None:
            if result_uid is not None and (
                existing.ext_id != ext_id
                or existing.status_code != status_code
                or existing.result != parsed
            ):
                log.warning(
                    "Conflicting result_uid task_id=%s uid=%s result_id=%s",
                    task_id,
                    result_uid,
                    existing.id,
                )
            await session.commit()
            return StoredTaskResult(
                existing.id,
                existing.ext_id,
                existing.status_code,
                existing.result,
                False,
                False,
            )

        inserted = await session.execute(
            insert(DevTaskResult)
            .values(
                task_id=task_id,
                ext_id=ext_id,
                status_code=status_code,
                result=parsed,
                result_uid=result_uid,
                result_fingerprint=fingerprint,
            )
            .returning(DevTaskResult.id)
        )
        result_id = inserted.scalar_one()
        was_expired = task_status.status == TaskStatus.EXPIRED or (
            task_status.status < TaskStatus.DONE
            and task_status.expires_at is not None
            and received_at >= task_status.expires_at
        )
        if task_status.status < TaskStatus.DONE:
            if was_expired:
                task_status.status = TaskStatus.EXPIRED
                task_status.ttl = 0
            else:
                task_status.status = TaskStatus.DONE
                if task_status.pending_at is None:
                    task_status.pending_at = received_at
                if task_status.initial_ttl == 0:
                    task_status.ttl = 0
                elif task_status.expires_at is not None:
                    seconds_left = (
                        task_status.expires_at - received_at
                    ).total_seconds()
                    task_status.ttl = max(0, ceil(seconds_left / 60))
        send_webhook = (
            not is_deleted
            and task_status.status != TaskStatus.DELETED
            and (
                not was_expired
                or (
                    task_status.expires_at is not None
                    and received_at <= task_status.expires_at + timedelta(minutes=3)
                )
            )
        )
        if send_webhook:
            # Resolve the registered recipient now, not after a device changes org.
            # No HTTP or broker operation participates in this transaction.
            await session.execute(
                insert(RpcResultWebhook).from_select(
                    ["result_id", "webhook_id"],
                    select(literal(result_id), OrgWebhook.id)
                    .select_from(DevTask)
                    .join(DeviceOrgBind, DeviceOrgBind.device_id == DevTask.device_id)
                    .join(OrgWebhook, OrgWebhook.org_id == DeviceOrgBind.org_id)
                    .where(
                        DevTask.id == task_id,
                        OrgWebhook.event_type == "msg-task-result",
                        OrgWebhook.is_active.is_(True),
                    )
                    .limit(1),
                )
            )
        if getattr(owner, "method_code", 0) == 7011:
            await cls.scrub_renewal_payload(session, [task_id])
        await session.commit()
        return StoredTaskResult(
            result_id, ext_id, status_code, parsed, True, send_webhook
        )
