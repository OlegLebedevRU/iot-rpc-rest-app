from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.dialects import postgresql

from core.integrations.webhooks import Webhook, WebhookConfig
from core.services import rpc_result_webhooks as worker


def setup_delivery(monkeypatch, *, attempts=0, error=None, active=True, expired=False):
    now = datetime.now(UTC)
    delivery = SimpleNamespace(
        attempts=attempts,
        expires_at=now + timedelta(minutes=-1 if expired else 30),
        next_attempt_at=now,
        finished_at=None,
        last_error=None,
    )
    result = SimpleNamespace(id=71, ext_id=0, status_code=200, result={"ok": True})
    task = SimpleNamespace(id=uuid4(), device_id=999)
    webhook = SimpleNamespace(
        org_id=4, headers={}, url="https://example.test/hook", is_active=active
    )
    row = (delivery, result, task, webhook, now)
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(one_or_none=lambda: row))
    )
    client = AsyncMock()
    client.send.side_effect = error
    constructor = AsyncMock()
    constructor.__aenter__.return_value = client
    monkeypatch.setattr(worker, "Webhook", lambda **kwargs: constructor)
    return session, delivery, client


@pytest.mark.anyio
async def test_delivery_success_and_queue_only_lock(monkeypatch):
    session, delivery, client = setup_delivery(monkeypatch)
    assert await worker.deliver_one(session)
    client.send.assert_awaited_once_with({"ok": True})
    assert delivery.attempts == 1
    assert delivery.finished_at is not None
    assert delivery.last_error is None
    sql = str(session.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE OF tb_rpc_result_webhooks SKIP LOCKED" in sql


@pytest.mark.anyio
async def test_transient_failures_get_bounded_persisted_backoff(monkeypatch):
    for attempt, delay in enumerate(worker.RETRY_DELAYS):
        session, delivery, _ = setup_delivery(
            monkeypatch, attempts=attempt, error=httpx.ConnectError("failed")
        )
        before = delivery.next_attempt_at
        await worker.deliver_one(session)
        assert delivery.next_attempt_at == before + timedelta(seconds=delay)
        assert delivery.finished_at is None
    session, delivery, _ = setup_delivery(
        monkeypatch, attempts=5, error=httpx.ConnectError("failed")
    )
    await worker.deliver_one(session)
    assert delivery.attempts == 6
    assert delivery.finished_at is not None


@pytest.mark.anyio
async def test_expired_and_disabled_deliveries_do_not_send(monkeypatch):
    for active, expired in ((False, False), (True, True)):
        session, delivery, client = setup_delivery(
            monkeypatch, active=active, expired=expired
        )
        await worker.deliver_one(session)
        client.send.assert_not_awaited()
        assert delivery.finished_at is not None
        assert delivery.attempts == 0


@pytest.mark.anyio
async def test_http_status_retry_policy(monkeypatch):
    for code, retry in (
        (400, False),
        (401, False),
        (404, False),
        (408, True),
        (429, True),
        (500, True),
        (503, True),
    ):
        response = httpx.Response(
            code, request=httpx.Request("POST", "https://example.test")
        )
        error = httpx.HTTPStatusError(
            "failed", request=response.request, response=response
        )
        session, delivery, _ = setup_delivery(monkeypatch, error=error)
        await worker.deliver_one(session)
        assert (delivery.finished_at is None) is retry
        assert delivery.last_error == f"http_{code}"


@pytest.mark.anyio
async def test_existing_http_client_retries_503_then_succeeds(monkeypatch):
    request = httpx.Request("POST", "https://example.test")
    sleep = AsyncMock()
    monkeypatch.setattr("core.integrations.webhooks.asyncio.sleep", sleep)
    async with Webhook(str(request.url), WebhookConfig(max_retries=2)) as client:
        client.client.post = AsyncMock(
            side_effect=[
                httpx.Response(503, request=request),
                httpx.Response(429, request=request),
                httpx.Response(200, request=request),
            ]
        )
        assert (await client.send({})).status_code == 200
        assert client.client.post.await_count == 3
    assert [call.args[0] for call in sleep.await_args_list] == [0.5, 1.0]
