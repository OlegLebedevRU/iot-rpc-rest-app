"""Dedicated issuer startup and transport-role isolation."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import run_camera_runtime as module


@pytest.fixture
def dependencies(monkeypatch):
    broker = SimpleNamespace(_subscribers={}, start=AsyncMock(), stop=AsyncMock())
    redis = SimpleNamespace(
        init_pool=AsyncMock(), ping=AsyncMock(return_value=True), close_pool=AsyncMock()
    )
    db = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(module, "fs_router", SimpleNamespace(broker=broker))
    monkeypatch.setattr(module, "redis_helper", redis)
    monkeypatch.setattr(module, "db_helper", db)
    monkeypatch.setattr(module.settings.camera, "monotonic_runtime_enabled", True)
    return broker, redis, db


@pytest.mark.anyio
async def test_worker_is_owned_executor_and_closes_resources_on_cancel(
    dependencies, monkeypatch
):
    broker, redis, db = dependencies
    seen = []

    async def loop(runtime):
        seen.append(runtime)
        raise asyncio.CancelledError

    monkeypatch.setattr(module, "camera_runtime_loop", loop)
    with pytest.raises(asyncio.CancelledError):
        await module.run_worker()
    assert len(seen) == 1 and seen[0].owns_issuer
    broker.start.assert_awaited_once()
    broker.stop.assert_awaited_once()
    redis.close_pool.assert_awaited_once()
    db.dispose.assert_awaited_once()


@pytest.mark.anyio
async def test_worker_refuses_shared_consumers(dependencies):
    broker, _, _ = dependencies
    broker._subscribers = {1: object()}
    with pytest.raises(RuntimeError, match="must_not_consume_shared_queues"):
        await module.run_worker()
    broker.start.assert_not_awaited()


@pytest.mark.anyio
async def test_worker_disabled_does_not_start(dependencies, monkeypatch):
    broker, _, _ = dependencies
    monkeypatch.setattr(module.settings.camera, "monotonic_runtime_enabled", False)
    with pytest.raises(RuntimeError, match="camera_runtime_disabled"):
        await module.run_worker()
    broker.start.assert_not_awaited()


@pytest.mark.anyio
async def test_worker_connection_failure_never_executes_jobs(dependencies, monkeypatch):
    broker, redis, db = dependencies
    broker.start.side_effect = OSError("unavailable")
    loop = AsyncMock()
    monkeypatch.setattr(module, "camera_runtime_loop", loop)
    with pytest.raises(OSError, match="unavailable"):
        await module.run_worker()
    loop.assert_not_awaited()
    broker.stop.assert_awaited_once()
    redis.close_pool.assert_awaited_once()
    db.dispose.assert_awaited_once()


@pytest.mark.anyio
async def test_shutdown_failure_still_closes_database_and_redis(
    dependencies, monkeypatch
):
    broker, redis, db = dependencies
    broker.stop.side_effect = OSError("shutdown failed")
    monkeypatch.setattr(module, "camera_runtime_loop", AsyncMock())
    with pytest.raises(OSError, match="shutdown failed"):
        await module.run_worker()
    redis.close_pool.assert_awaited_once()
    db.dispose.assert_awaited_once()
