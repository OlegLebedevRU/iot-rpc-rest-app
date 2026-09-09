from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status
from starlette.datastructures import Headers, QueryParams

from api.internal_v1 import diagnostics as diagnostics_api
from core.config import settings
from core.remote_input.leases import lease_registry


class DummyWebSocket:
    def __init__(
        self,
        headers: dict[str, str],
        query_params: dict[str, str] | None = None,
    ) -> None:
        self.headers = Headers(headers)
        self.query_params = QueryParams(query_params or {})
        self.accepted = False
        self.close_code: int | None = None
        self.close_reason: str | None = None
        self.sent_messages: list[dict] = []
        self.receive_queue: asyncio.Queue[str] = asyncio.Queue()

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.close_code = code
        self.close_reason = reason

    async def send_json(self, message: dict) -> None:
        self.sent_messages.append(message)

    async def receive_text(self) -> str:
        # If queue is empty in tests, disconnect
        try:
            return await asyncio.wait_for(self.receive_queue.get(), timeout=0.05)
        except TimeoutError, asyncio.TimeoutError:
            from fastapi import WebSocketDisconnect

            raise WebSocketDisconnect()


@pytest.fixture(autouse=True)
async def cleanup_leases():
    yield
    async with lease_registry._lock:
        lease_registry._leases_by_id.clear()
        lease_registry._active_by_sn.clear()
        lease_registry._active_ws_leases.clear()


@pytest.mark.asyncio
async def test_resolve_websocket_org_id_does_not_accept_api_key() -> None:
    websocket = DummyWebSocket({"x-api-key": "test"})

    assert (
        await diagnostics_api._resolve_websocket_org_id(cast(WebSocket, websocket))
        is None
    )


@pytest.mark.asyncio
async def test_resolve_websocket_org_id_from_forwarded_header() -> None:
    cases = [
        ({"X-Role": "superuser", "orgId": "42"}, {}, 42),
        ({"X-Role": "admin", "orgid": "43"}, {}, 43),
        ({"X-User-Id": "1", "orgId": "44"}, {}, 44),
        ({"jwt-role": "admin", "jwt-org": "45"}, {}, 45),
        ({"X-Role-Id": "1", "X-Org-Id": "46"}, {}, 46),
        ({"X-Role": "superuser"}, {"org_id": "47"}, 47),
        ({"X-Role": "superuser", "orgId": "bad"}, {}, None),
        ({"X-Role": "superuser"}, {}, None),
        ({"orgId": "42"}, {}, None),  # Rejected because not superuser
        ({}, {}, None),
    ]

    for headers, query_params, expected in cases:
        websocket = DummyWebSocket(headers, query_params=query_params)

        assert (
            await diagnostics_api._resolve_websocket_org_id(cast(WebSocket, websocket))
            == expected
        )


@pytest.mark.asyncio
async def test_is_websocket_device_allowed_checks_sn_and_org(monkeypatch) -> None:
    calls = []

    async def fake_get_device_id(*, session, sn, org_id):
        calls.append((session, sn, org_id))
        return 123

    monkeypatch.setattr(diagnostics_api.DeviceRepo, "get_device_id", fake_get_device_id)
    session = cast(AsyncSession, object())

    assert (
        await diagnostics_api._is_websocket_device_allowed(
            session, sn="SN001", org_id=7
        )
        is True
    )
    assert calls == [(session, "SN001", 7)]


@pytest.mark.asyncio
async def test_diagnostics_ws_rejects_missing_org_id_before_accept() -> None:
    websocket = DummyWebSocket({})

    await diagnostics_api.diagnostics_ws(
        cast(WebSocket, websocket), "SN001", cast(AsyncSession, object())
    )

    assert websocket.accepted is False
    assert websocket.close_code == status.WS_1008_POLICY_VIOLATION


@pytest.mark.asyncio
async def test_diagnostics_ws_rejects_foreign_device_before_accept(monkeypatch) -> None:
    async def fake_is_allowed(session, *, sn, org_id):
        return False

    monkeypatch.setattr(
        diagnostics_api, "_is_websocket_device_allowed", fake_is_allowed
    )
    websocket = DummyWebSocket({"X-Role": "superuser", "orgId": "7"})

    await diagnostics_api.diagnostics_ws(
        cast(WebSocket, websocket), "SN001", cast(AsyncSession, object())
    )

    assert websocket.accepted is False
    assert websocket.close_code == status.WS_1008_POLICY_VIOLATION


@pytest.mark.asyncio
async def test_diagnostics_ws_with_valid_console_lease(monkeypatch) -> None:
    async def fake_allowed(*a, **k):
        return True

    monkeypatch.setattr(diagnostics_api, "_is_websocket_device_allowed", fake_allowed)

    lease = await lease_registry.acquire(
        org_id=7,
        device_id=123,
        sn="SN001",
        owner_user_id="su_admin",
        owner_role="superuser",
        ttl_sec=60,
        scope="console",
        owner_session_id="sess_123",
    )

    websocket = DummyWebSocket(
        headers={
            "X-Role": "superuser",
            "orgId": "7",
            "X-User-Id": "su_admin",
            "X-Session-Id": "sess_123",
        },
        query_params={"lease_id": str(lease.lease_id)},
    )

    await diagnostics_api.diagnostics_ws(
        cast(WebSocket, websocket), "SN001", cast(AsyncSession, object())
    )

    assert websocket.accepted is True


@pytest.mark.asyncio
async def test_diagnostics_ws_implicit_console_lease(monkeypatch) -> None:
    async def fake_allowed(*a, **k):
        return True

    monkeypatch.setattr(diagnostics_api, "_is_websocket_device_allowed", fake_allowed)

    async def fake_get_dev(*a, **k):
        return 123

    monkeypatch.setattr(diagnostics_api.DeviceRepo, "get_device_id", fake_get_dev)
    monkeypatch.setattr(settings.diagnostics, "implicit_console_lease", True)

    websocket = DummyWebSocket(
        headers={
            "X-Role": "superuser",
            "orgId": "7",
            "X-User-Id": "su_admin",
            "X-Session-Id": "sess_implicit",
        },
    )

    await diagnostics_api.diagnostics_ws(
        cast(WebSocket, websocket), "SN001", cast(AsyncSession, object())
    )

    assert websocket.accepted is True
    # First message sent over WS must be {"type": "lease", "lease_id": ...}
    assert len(websocket.sent_messages) >= 1
    first_msg = websocket.sent_messages[0]
    assert first_msg["type"] == "lease"
    assert "lease_id" in first_msg

    active = await lease_registry.get_active("SN001")
    assert active is not None
    assert active.scope == "console"


@pytest.mark.asyncio
async def test_diagnostics_ws_rejects_foreign_lease(monkeypatch) -> None:
    async def fake_allowed(*a, **k):
        return True

    monkeypatch.setattr(diagnostics_api, "_is_websocket_device_allowed", fake_allowed)

    lease = await lease_registry.acquire(
        org_id=7,
        device_id=123,
        sn="SN001",
        owner_user_id="su_admin_1",
        owner_role="superuser",
        ttl_sec=60,
        scope="console",
        owner_session_id="sess_1",
    )

    # Different user connects with this lease_id
    websocket = DummyWebSocket(
        headers={
            "X-Role": "superuser",
            "orgId": "7",
            "X-User-Id": "su_admin_2",
            "X-Session-Id": "sess_2",
        },
        query_params={"lease_id": str(lease.lease_id)},
    )

    await diagnostics_api.diagnostics_ws(
        cast(WebSocket, websocket), "SN001", cast(AsyncSession, object())
    )

    assert websocket.accepted is False
    assert websocket.close_code == 4409
    assert websocket.close_reason == "lease_not_owner"


@pytest.mark.asyncio
async def test_diagnostics_ws_rejects_active_stream_lease(monkeypatch) -> None:
    async def fake_allowed(*a, **k):
        return True

    async def fake_get_dev(*a, **k):
        return 123

    monkeypatch.setattr(diagnostics_api, "_is_websocket_device_allowed", fake_allowed)
    monkeypatch.setattr(diagnostics_api.DeviceRepo, "get_device_id", fake_get_dev)

    # Active stream lease exists on SN
    stream_lease = await lease_registry.acquire(
        org_id=7,
        device_id=123,
        sn="SN001",
        owner_user_id="operator",
        owner_role="user",
        ttl_sec=60,
        scope="stream",
        owner_session_id="sess_op",
    )

    # Superuser tries to connect without lease_id (implicit acquire hits conflict)
    websocket = DummyWebSocket(
        headers={
            "X-Role": "superuser",
            "orgId": "7",
            "X-User-Id": "su_admin",
            "X-Session-Id": "sess_su",
        },
    )

    await diagnostics_api.diagnostics_ws(
        cast(WebSocket, websocket), "SN001", cast(AsyncSession, object())
    )

    assert websocket.accepted is False
    assert websocket.close_code == 4409
    assert websocket.close_reason == "lease_busy"

    # Superuser passes stream lease_id -> rejected due to scope mismatch
    ws_stream_id = DummyWebSocket(
        headers={
            "X-Role": "superuser",
            "orgId": "7",
            "X-User-Id": "operator",
            "X-Session-Id": "sess_op",
        },
        query_params={"lease_id": str(stream_lease.lease_id)},
    )

    await diagnostics_api.diagnostics_ws(
        cast(WebSocket, ws_stream_id), "SN001", cast(AsyncSession, object())
    )

    assert ws_stream_id.accepted is False
    assert ws_stream_id.close_code == 4409
    assert ws_stream_id.close_reason == "scope_mismatch"


@pytest.mark.asyncio
async def test_diagnostics_ws_disconnect_grace_and_revoke(monkeypatch) -> None:
    async def fake_allowed(*a, **k):
        return True

    monkeypatch.setattr(diagnostics_api, "_is_websocket_device_allowed", fake_allowed)

    lease = await lease_registry.acquire(
        org_id=7,
        device_id=123,
        sn="SN_DIAG_DISC",
        owner_user_id="su_admin",
        owner_role="superuser",
        ttl_sec=60,
        scope="console",
        owner_session_id="sess_diag",
    )

    websocket = DummyWebSocket(
        headers={
            "X-Role": "superuser",
            "orgId": "7",
            "X-User-Id": "su_admin",
            "X-Session-Id": "sess_diag",
        },
        query_params={"lease_id": str(lease.lease_id)},
    )

    await diagnostics_api.diagnostics_ws(
        cast(WebSocket, websocket), "SN_DIAG_DISC", cast(AsyncSession, object())
    )

    assert websocket.accepted is True
    # WS disconnected -> lease marked disconnected
    assert lease.ws_disconnected_at is not None

    # Simulate grace period expired
    lease.ws_disconnected_at = datetime.now(UTC) - timedelta(seconds=15)
    expired = await lease_registry.cleanup_expired()
    assert len(expired) == 1
    assert await lease_registry.get_active("SN_DIAG_DISC") is None
