from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aio_pika import Message
from sqlalchemy.dialects import postgresql

from core.crud.dev_tasks_repo import TasksRepository
from core.models.common import TaskStatus
from core.schemas.device_tasks import TaskCreate, TaskResponse
from core.services import device_task_processing


class FakeQueryResult:
    def __init__(self, value):
        self.value = value

    @property
    def rowcount(self):
        return self.value.rowcount

    def one_or_none(self):
        return self.value

    def first(self):
        return self.value

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def mappings(self):
        return self


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.statements = []
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def execute(self, statement):
        statement.compile(dialect=postgresql.dialect())
        self.statements.append(statement)
        if (
            getattr(getattr(statement, "table", None), "name", None)
            == "tb_rpc_result_webhooks"
        ):
            return FakeQueryResult(None)
        return FakeQueryResult(next(self.responses))


@pytest.mark.asyncio
async def test_expired_result_webhook_window():
    now = datetime.now(UTC)
    for delay, send_webhook in (
        (timedelta(minutes=2), True),
        (timedelta(minutes=3), True),
        (timedelta(minutes=3, microseconds=1), False),
    ):
        task_id = uuid4()
        status = SimpleNamespace(
            status=TaskStatus.EXPIRED,
            ttl=0,
            expires_at=now - delay,
        )
        session = FakeSession(
            [
                SimpleNamespace(id=task_id, is_deleted=False),
                status,
                None,
                91,
            ]
        )

        result = await TasksRepository.record_result(
            session,
            task_id,
            "SN_TEST",
            0,
            200,
            {"status": "ok"},
            None,
            now,
        )

        assert result.result_id == 91
        assert result.is_new is True
        assert result.send_webhook is send_webhook
        assert status.status == TaskStatus.EXPIRED
        assert (len(session.statements) == 5) is send_webhook
        session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_result_after_delete_is_saved_without_webhook():
    task_id = uuid4()
    status = SimpleNamespace(
        status=TaskStatus.DELETED,
        ttl=0,
        expires_at=datetime.now(UTC),
    )
    session = FakeSession(
        [
            SimpleNamespace(id=task_id, is_deleted=True),
            status,
            None,
            92,
        ]
    )

    result = await TasksRepository.record_result(
        session,
        task_id,
        "SN_TEST",
        0,
        200,
        {},
        None,
        datetime.now(UTC),
    )

    assert result.result_id == 92
    assert result.send_webhook is False
    assert status.status == TaskStatus.DELETED


@pytest.mark.asyncio
async def test_new_active_result_finishes_task_in_same_commit():
    now = datetime.now(UTC)
    task_id = uuid4()
    status = SimpleNamespace(
        status=TaskStatus.LOCK,
        ttl=2,
        initial_ttl=2,
        pending_at=None,
        expires_at=now + timedelta(minutes=2),
    )
    session = FakeSession(
        [SimpleNamespace(id=task_id, is_deleted=False), status, None, 93]
    )

    result = await TasksRepository.record_result(
        session, task_id, "SN_TEST", 0, 200, {}, None, now
    )

    assert result.is_new is True
    assert result.send_webhook is True
    assert status.status == TaskStatus.DONE
    assert status.pending_at == now
    assert status.ttl == 2
    assert session.statements[-1].table.name == "tb_rpc_result_webhooks"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_result_after_deadline_marks_active_task_expired():
    now = datetime.now(UTC)
    task_id = uuid4()
    status = SimpleNamespace(
        status=TaskStatus.LOCK,
        ttl=1,
        expires_at=now - timedelta(seconds=30),
    )
    session = FakeSession(
        [SimpleNamespace(id=task_id, is_deleted=False), status, None, 94]
    )

    result = await TasksRepository.record_result(
        session, task_id, "SN_TEST", 0, 200, {}, None, now
    )

    assert status.status == TaskStatus.EXPIRED
    assert status.ttl == 0
    assert result.send_webhook is True


@pytest.mark.asyncio
async def test_duplicate_uid_returns_first_result_without_insert():
    task_id, result_uid = uuid4(), uuid4()
    status = SimpleNamespace(status=TaskStatus.DONE)
    first = SimpleNamespace(
        id=77,
        ext_id=3,
        status_code=200,
        result={"status": "first"},
    )
    session = FakeSession(
        [
            SimpleNamespace(id=task_id, is_deleted=False),
            status,
            first,
        ]
    )

    result = await TasksRepository.record_result(
        session,
        task_id,
        "SN_TEST",
        4,
        500,
        {"status": "changed"},
        result_uid,
        datetime.now(UTC),
    )

    assert (result.result_id, result.ext_id, result.status_code) == (77, 3, 200)
    assert result.result == {"status": "first"}
    assert result.is_new is False
    assert result.send_webhook is False
    assert len(session.statements) == 3


def test_legacy_fingerprint_normalizes_object_key_order():
    first = TasksRepository.result_fingerprint(0, 200, {"a": 1, "b": 2})
    second = TasksRepository.result_fingerprint(0, 200, {"b": 2, "a": 1})
    assert first == second
    assert first != TasksRepository.result_fingerprint(0, 500, {"a": 1, "b": 2})


def test_amqp_expiration_is_seconds_not_milliseconds():
    assert (
        Message(b"", expiration=timedelta(minutes=1)).properties.expiration == "60000"
    )


@pytest.mark.asyncio
async def test_zero_ttl_trigger_gets_internal_one_minute_transport_window(monkeypatch):
    published = AsyncMock()
    monkeypatch.setattr(device_task_processing.topic_publisher, "publish", published)
    task = TaskCreate(ext_task_id="trigger", device_id=1, method_code=51, ttl=0)
    created = TaskResponse(id=uuid4(), created_at=123)

    await device_task_processing.send_tsk("SN_TEST", task, created)

    assert published.await_args.kwargs["expiration"] == timedelta(minutes=1)
    assert published.await_args.kwargs["message"].header.ttl == 0


@pytest.mark.asyncio
async def test_addressed_task_query_is_bound_to_device_sn():
    session = FakeSession([None])
    await TasksRepository.select_task_by_id(session, uuid4(), 7099, sn="SN_TEST")
    query = str(session.statements[0])
    assert ".sn =" in query
    assert "expires_at >" in query


@pytest.mark.asyncio
async def test_expiration_job_depends_on_deadline_not_tick_count():
    session = FakeSession([SimpleNamespace(rowcount=0)])
    await TasksRepository.tasks_ttl_update(session, delta_ttl=99)
    query = str(session.statements[0])
    assert "expires_at <=" in query
    assert "status <" in query
    assert "ttl -" not in query
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_late_ack_cannot_restore_terminal_status():
    session = FakeSession([uuid4(), SimpleNamespace(rowcount=0)])
    updated = await TasksRepository.task_status_update(
        session, uuid4(), TaskStatus.PENDING, sn="SN_TEST"
    )
    query = str(session.statements[1])
    assert updated is False
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()
    assert "status =" in query
    assert "expires_at >" in query
    assert ".sn =" in query


@pytest.mark.asyncio
async def test_ack_applies_successful_guarded_update():
    session = FakeSession([uuid4(), SimpleNamespace(rowcount=1)])
    assert await TasksRepository.task_status_update(
        session, uuid4(), TaskStatus.PENDING, sn="SN_TEST"
    )
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_result_preserves_zero_ttl_and_rounds_positive_remainder_up():
    now = datetime.now(UTC)
    for initial_ttl, seconds, expected_ttl in ((0, 45, 0), (2, 60.1, 2), (1, 0.1, 1)):
        task_id = uuid4()
        status = SimpleNamespace(
            status=TaskStatus.LOCK,
            ttl=initial_ttl,
            initial_ttl=initial_ttl,
            pending_at=None,
            expires_at=now + timedelta(seconds=seconds),
        )
        session = FakeSession(
            [
                SimpleNamespace(id=task_id, is_deleted=False),
                status,
                None,
                95,
            ]
        )
        result = await TasksRepository.record_result(
            session, task_id, "SN_TEST", 0, 200, {}, None, now
        )
        assert result.is_new is True
        assert status.status == TaskStatus.DONE
        assert status.ttl == expected_ttl


@pytest.mark.asyncio
async def test_trigger_transport_uses_remaining_window(monkeypatch):
    published = AsyncMock()
    monkeypatch.setattr(device_task_processing.topic_publisher, "publish", published)
    task = TaskCreate(ext_task_id="trigger", device_id=1, method_code=51, ttl=0)
    await device_task_processing.send_tsk(
        "SN_TEST", task, TaskResponse(id=uuid4(), created_at=123), expiration=12.5
    )
    assert published.await_args.kwargs["expiration"] == 12.5
    assert published.await_args.kwargs["message"].header.ttl == 0


@pytest.mark.asyncio
async def test_create_task_deadline_is_bound_to_stored_creation_time():
    session = FakeSession([123, None, None])
    result = await TasksRepository.create_task(
        session, TaskCreate(ext_task_id="trigger", device_id=1, method_code=51, ttl=0)
    )
    assert result is not None
    status_insert = session.statements[2].compile(dialect=postgresql.dialect())
    assert "SELECT tb_dev_tasks.created_at" in str(status_insert)
    assert timedelta(minutes=1) in status_insert.params.values()
    assert status_insert.params["initial_ttl"] == 0
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_updates_task_before_status_in_single_commit():
    task_id = uuid4()
    session = FakeSession([1, SimpleNamespace(deleted_at=123), None])
    deleted = await TasksRepository.delete_task(session, task_id, 1)
    assert deleted.id == task_id
    assert session.statements[1].table.name == "tb_dev_tasks"
    assert session.statements[2].table.name == "tb_dev_tasks_status"
    session.commit.assert_awaited_once()
