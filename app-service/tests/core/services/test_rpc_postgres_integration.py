"""Opt-in checks against an isolated migrated database, never production.

Set RPC_TEST_DB_URL to the dedicated /rpc_test database and seed org/device 1,
RPC_TEST_SN and an active msg-task-result webhook before running this module.
HTTP is substituted; PostgreSQL transactions and locks are real.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.crud.dev_tasks_repo import TasksRepository
from core.models.common import TaskStatus
from core.models.device_tasks import DevTaskResult, DevTaskStatus, RpcResultWebhook
from core.schemas.device_tasks import TaskCreate
from core.services import rpc_result_webhooks as worker

URL = os.environ.get("RPC_TEST_DB_URL", "")
pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not URL, reason="isolated PostgreSQL not configured"),
]


async def test_real_postgres_rpc_lifecycle_and_delivery(monkeypatch):
    assert URL.endswith("/rpc_test"), "Only isolated rpc_test database is allowed"
    engine = create_async_engine(URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def create(ttl=5):
        async with sessions() as session:
            result = await TasksRepository.create_task(
                session,
                TaskCreate(
                    device_id=1,
                    method_code=51,
                    ttl=ttl,
                    ext_task_id="rpc-integration",
                ),
            )
            assert result is not None
            return result[0]

    async def record(task_id, uid, payload=None, now=None, sn="RPC_TEST_SN"):
        async with sessions() as session:
            return await TasksRepository.record_result(
                session,
                task_id,
                sn,
                0,
                200,
                payload or {"ok": True},
                uid,
                now or datetime.now(UTC),
            )

    try:
        task_id, uid = await create(), uuid4()
        # Separate connections race on the same UID: one result and one delivery.
        results = await asyncio.gather(*(record(task_id, uid) for _ in range(8)))
        assert sum(result.is_new for result in results) == 1
        result_id = results[0].result_id
        assert {result.result_id for result in results} == {result_id}
        conflict = await record(task_id, uid, {"different": True})
        assert conflict.result_id == result_id and conflict.result == {"ok": True}
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(DevTaskResult)
                    .where(DevTaskResult.task_id == task_id)
                )
                == 1
            )
            assert await session.get(RpcResultWebhook, result_id) is not None
            assert not await TasksRepository.task_status_update(
                session, task_id, TaskStatus.PENDING, sn="RPC_TEST_SN"
            )

        # Other devices cannot request, ACK or submit a result for this task.
        foreign_task = await create()
        assert await record(foreign_task, uuid4(), sn="OTHER_SN") is None
        async with sessions() as session:
            assert (
                await TasksRepository.select_task_by_id(
                    session, foreign_task, sn="OTHER_SN"
                )
                is None
            )
            assert not await TasksRepository.task_status_update(
                session, foreign_task, TaskStatus.PENDING, sn="OTHER_SN"
            )

        # Legacy normalization and zero-TTL completion retain the external contract.
        zero = await create(ttl=0)
        first = await record(zero, None, {"a": 1, "b": 2})
        repeated = await record(zero, None, {"b": 2, "a": 1})
        assert first.result_id == repeated.result_id
        async with sessions() as session:
            status = await session.scalar(
                select(DevTaskStatus).where(DevTaskStatus.task_id == zero)
            )
            assert status.ttl == 0 and status.status == TaskStatus.DONE

        # Race result vs DELETE: state stays deleted, and subsequent results cannot notify.
        deleted = await create()

        async def delete():
            async with sessions() as session:
                assert await TasksRepository.delete_task(session, deleted, 1)

        await asyncio.gather(record(deleted, uuid4()), delete())
        late = await record(deleted, uuid4())
        async with sessions() as session:
            assert await session.get(RpcResultWebhook, late.result_id) is None
            assert (
                await session.scalar(
                    select(DevTaskStatus.status).where(DevTaskStatus.task_id == deleted)
                )
                == TaskStatus.DELETED
            )

        # Both sides of the inclusive three-minute boundary; expiration is idempotent.
        for offset, expected in ((180, True), (180.001, False)):
            expired = await create()
            now = datetime.now(UTC)
            async with sessions() as session:
                await session.execute(
                    update(DevTaskStatus)
                    .where(DevTaskStatus.task_id == expired)
                    .values(expires_at=now - timedelta(seconds=offset))
                )
                await session.commit()
                await TasksRepository.tasks_ttl_update(session)
                await TasksRepository.tasks_ttl_update(session)
            late = await record(expired, uuid4(), now=now)
            async with sessions() as session:
                assert (
                    await session.get(RpcResultWebhook, late.result_id) is not None
                ) is expected
                assert (
                    await session.scalar(
                        select(DevTaskStatus.status).where(
                            DevTaskStatus.task_id == expired
                        )
                    )
                    == TaskStatus.EXPIRED
                )

        # Isolate one delivery for restart/retry and two-worker exclusion checks.
        async with sessions() as session:
            await session.execute(
                update(RpcResultWebhook)
                .where(RpcResultWebhook.result_id != result_id)
                .values(finished_at=func.now())
            )
            await session.commit()
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        fail = True

        async def send(self, payload):
            calls.append(payload)
            entered.set()
            await release.wait()
            if fail:
                raise httpx.ConnectError("test failure")
            return httpx.Response(200)

        monkeypatch.setattr(worker.Webhook, "send", send)

        async def deliver():
            async with sessions() as session:
                async with session.begin():
                    return await worker.deliver_one(session)

        running = asyncio.create_task(deliver())
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert await deliver() is False  # SKIP LOCKED: no simultaneous HTTP retry.
        release.set()
        assert await running
        async with sessions() as session:
            pending = await session.get(RpcResultWebhook, result_id)
            assert pending.attempts == 1 and pending.finished_at is None
            assert pending.last_error == "ConnectError"
            pending.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        fail = False
        assert await deliver()  # New session resumes the persisted retry.
        assert len(calls) == 2
        async with sessions() as session:
            completed = await session.get(RpcResultWebhook, result_id)
            assert completed.finished_at is not None and completed.attempts == 2
        await record(task_id, uid)
        assert not await deliver()  # Duplicate RES cannot restart completed delivery.
    finally:
        await engine.dispose()
