"""Actual SQL histories: transfer does not disclose old task payload/results/events."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import BigInteger, create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateColumn
from sqlalchemy.sql.elements import Extract, BinaryExpression

from core.models import (
    Device,
    DeviceAuditLog,
    DeviceOrgBind,
    DeviceProvisioning,
    DeviceTag,
    Org,
)
from core.models.device_events import DevEvent
from core.models.device_tasks import (
    DevTask,
    DevTaskPayload,
    DevTaskResult,
    DevTaskStatus,
)
from core.models.remote_sessions import RemoteSession
from core.crud.dev_tasks_repo import TasksRepository
from core.crud.dev_events_repo import EventRepository
from core.schemas.device_tasks import TaskCreate
from core.services import identity_transfer as transfer


@compiles(Extract, "sqlite")
def extract_epoch(element, compiler, **kwargs):
    if element.field.lower() == "epoch":
        expr = element.expr
        if isinstance(expr, BinaryExpression):
            return f"((julianday({compiler.process(expr.left, **kwargs)}) - julianday({compiler.process(expr.right, **kwargs)})) * 86400)"
        return f"strftime('%s', {compiler.process(expr, **kwargs)})"
    return compiler.visit_extract(element, **kwargs)


@compiles(BigInteger, "sqlite")
def bigint_type(element, compiler, **kwargs):
    return "INTEGER"


@compiles(JSONB, "sqlite")
def json_type(element, compiler, **kwargs):
    return "JSON"


@compiles(CreateColumn, "sqlite")
def timestamp_default(element, compiler, **kwargs):
    return (
        compiler.visit_create_column(element, **kwargs)
        .replace("CURRENT_TIMESTAMP(0)", "CURRENT_TIMESTAMP")
        .replace("CURRENT_TIMESTAMP(3)", "CURRENT_TIMESTAMP")
        .replace("::jsonb", "")
    )


@pytest.mark.anyio
async def test_transfer_preserves_source_history_and_rejects_late_results(monkeypatch):
    from core.models import Base

    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def setup(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.create_function(
            "clock_timestamp",
            0,
            lambda: datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        )
        connection.create_function(
            "greatest", -1, lambda *args: max(arg for arg in args if arg is not None)
        )
        connection.create_function(
            "ceil", 1, lambda value: __import__("math").ceil(value)
        )

    classes = (
        Device,
        DeviceAuditLog,
        DeviceOrgBind,
        DeviceProvisioning,
        DeviceTag,
        Org,
        DevEvent,
        DevTask,
        DevTaskPayload,
        DevTaskResult,
        DevTaskStatus,
        RemoteSession,
    )
    Base.metadata.create_all(engine, tables=[model.__table__ for model in classes])
    session = Session(engine, expire_on_commit=False)

    class Adapter:
        add = session.add

        async def execute(self, statement, *args):
            return session.execute(statement, *args)

        async def scalar(self, statement):
            return session.scalar(statement)

        async def scalars(self, statement):
            return session.scalars(statement)

        async def flush(self):
            session.flush()

        async def commit(self):
            session.commit()

        async def rollback(self):
            session.rollback()

    db = Adapter()
    now = datetime.now(UTC)
    session.add_all(
        [
            Org(org_id=1, name="fixture-A", is_deleted=False),
            Org(org_id=2, name="fixture-B", is_deleted=False),
        ]
    )
    session.flush()
    session.add(Device(device_id=773, sn="fixture-history", is_deleted=False))
    session.flush()
    session.add(DeviceOrgBind(device_id=773, org_id=1))
    old_id = uuid4()
    session.add(
        DevTask(
            id=old_id,
            device_id=773,
            org_id=None,
            method_code=101,
            ext_task_id="old",
            created_at=now,
            is_deleted=False,
        )
    )
    session.flush()
    session.add_all(
        [
            DevTaskStatus(
                task_id=old_id,
                status=0,
                ttl=5,
                initial_ttl=5,
                expires_at=now + timedelta(minutes=5),
            ),
            DevTaskPayload(task_id=old_id, payload={"private": "source-command"}),
            DevTaskResult(
                id=1,
                task_id=old_id,
                ext_id=1,
                status_code=200,
                result={"private": "source-output"},
            ),
            DevEvent(
                device_id=773,
                org_id=1,
                event_type_code=999,
                dev_event_id=1,
                dev_timestamp=now,
                payload={"private": "source-event"},
            ),
        ]
    )
    session.commit()
    monkeypatch.setattr(
        transfer,
        "lease_registry",
        SimpleNamespace(get_active_by_sn=AsyncMock(return_value=None)),
    )
    request = transfer.IdentityTransferRequest(
        operation_id=uuid4(),
        terminal_id=1,
        device_id=773,
        sn="fixture-history",
        source_org_id=1,
        target_org_id=2,
    )
    assert (await transfer.transfer_identity(db, request))["status"] == "completed"
    assert session.scalar(select(DevTask.org_id).where(DevTask.id == old_id)) == 1
    assert (
        session.scalar(
            select(DevTaskStatus.status).where(DevTaskStatus.task_id == old_id)
        )
        == 4
    )
    source, results = await TasksRepository.get_task(db, old_id, 1)
    assert source and source["payload"] == {"private": "source-command"}
    assert results and results[0]["result"] == {"private": "source-output"}
    assert await TasksRepository.get_task(db, old_id, 2) == (None, None)
    assert session.scalars(
        select(DevEvent.id).where(*EventRepository.tenant_conditions(1))
    ).all()
    assert (
        session.scalars(
            select(DevEvent.id).where(*EventRepository.tenant_conditions(2))
        ).all()
        == []
    )
    assert (
        await TasksRepository.record_result(
            db, old_id, "fixture-history", 2, 200, {"poison": "target"}, None, now
        )
        is None
    )
    assert session.scalar(select(DevTaskResult.result)) == {"private": "source-output"}
    new_id = uuid4()
    session.add(
        DevTask(
            id=new_id,
            device_id=773,
            org_id=2,
            method_code=101,
            created_at=now,
            is_deleted=False,
        )
    )
    session.commit()
    assert session.scalars(
        TasksRepository._apply_org_filter(select(DevTask.id), 1)
    ).all() == [old_id]
    assert session.scalars(
        TasksRepository._apply_org_filter(select(DevTask.id), 2)
    ).all() == [new_id]
    assert session.scalars(
        select(DevTask.id).where(TasksRepository._current_owner_condition())
    ).all() == [new_id]
    session.close()
    engine.dispose()


@pytest.mark.anyio
async def test_task_creation_rechecks_current_owner_and_persists_its_snapshot():
    task = TaskCreate(
        device_id=773, ext_task_id="fixture", method_code=101, ttl=5, payload={"dt": []}
    )
    db = AsyncMock()
    db.scalar.return_value = None
    with pytest.raises(HTTPException) as error:
        await TasksRepository.create_task(db, task, org_id=1)
    assert error.value.status_code == 403
    db.execute.assert_not_awaited()
    db.scalar.return_value = 2
    returned = MagicMock()
    returned.scalar_one.return_value = 1700000000
    db.execute.return_value = returned
    assert await TasksRepository.create_task(db, task, org_id=2)
    insert = db.execute.call_args_list[0].args[0]
    assert insert.compile().params["org_id"] == 2
    assert "FOR UPDATE" in str(db.scalar.call_args.args[0])
