from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from core.models.remote_sessions import RemoteSession
from core.redis_helper import redis_helper
from core.services.remote_session_event_service import RemoteSessionEventService
from redis.exceptions import ConnectionError


@pytest.mark.anyio
async def test_intermediate_beat_uses_cache_and_failure_checkpoints(monkeypatch):
    now = datetime.now(UTC)
    rec = RemoteSession(
        session_id="test", status="active", last_heartbeat_at=now - timedelta(seconds=5)
    )
    db = AsyncMock()
    db.scalar.return_value = rec
    cache = AsyncMock()
    monkeypatch.setattr(redis_helper, "get_client", lambda: cache)
    service = RemoteSessionEventService()
    result = await service.heartbeat(db, "test")
    assert result.last_heartbeat_at >= now
    cache.set.assert_awaited_once()
    db.flush.assert_not_awaited()
    cache.set.side_effect = ConnectionError()
    await service.heartbeat(db, "test")
    db.flush.assert_awaited_once()


@pytest.mark.anyio
async def test_stale_check_handles_cache_loss_with_bounded_grace(monkeypatch):
    now = datetime.now(UTC)
    rec = RemoteSession(
        session_id="test",
        status="active",
        last_heartbeat_at=now - timedelta(seconds=65),
    )
    db = AsyncMock()
    db.scalar.return_value = rec
    cache = AsyncMock()
    monkeypatch.setattr(redis_helper, "get_client", lambda: cache)
    service = RemoteSessionEventService()
    cache.get.return_value = str((now - timedelta(seconds=5)).timestamp())
    assert not await service._stale_under_lock(db, rec, now, 60)
    cache.get.return_value = None
    assert not await service._stale_under_lock(db, rec, now, 60)
    assert await service._stale_under_lock(db, rec, now + timedelta(seconds=31), 60)
