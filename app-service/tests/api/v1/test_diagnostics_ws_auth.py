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
async def test_resolve_websocket_org_requires_gateway_and_decision(monkeypatch) -> None:
    from uuid import uuid4

    gateway = str(uuid4())
    monkeypatch.setattr(settings.auth, "internal_service_key", gateway)
    for headers, expected in [
        ({"X-Role": "superuser", "X-Org-Id": "7"}, None),
        ({"X-Console-Org": "7"}, None),
        ({"X-Internal-Service-Key": gateway}, None),
        ({"X-Internal-Service-Key": gateway, "X-Console-Org": "7"}, 7),
    ]:
        assert (
            await diagnostics_api._resolve_websocket_org_id(
                cast(WebSocket, DummyWebSocket(headers))
            )
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


@pytest.fixture
def gateway_key(monkeypatch):
    from uuid import uuid4

    key = str(uuid4())
    monkeypatch.setattr(settings.auth, "internal_service_key", key)
    return key


@pytest.mark.asyncio
async def test_diagnostics_ws_with_valid_console_lease(
    monkeypatch, gateway_key
) -> None:
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
            "X-Internal-Service-Key": gateway_key,
            "X-Console-Expires": str(int(datetime.now(UTC).timestamp()) + 60),
            "X-Role": "superuser",
            "X-Console-Org": "7",
            "X-Console-User": "su_admin",
            "X-Console-Session": "sess_123",
        },
        query_params={"lease_id": str(lease.lease_id)},
    )

    await diagnostics_api.diagnostics_ws(
        cast(WebSocket, websocket), "SN001", cast(AsyncSession, object())
    )

    assert websocket.accepted is True


@pytest.mark.asyncio
async def test_owner_console_requires_matching_explicit_tenant_lease(
    monkeypatch,
    gateway_key,
) -> None:
    async def fake_allowed(*a, **k):
        return True

    monkeypatch.setattr(diagnostics_api, "_is_websocket_device_allowed", fake_allowed)
    lease = await lease_registry.acquire(
        org_id=7,
        device_id=123,
        sn="SN001",
        owner_user_id="owner",
        owner_role="l4desk_owner",
        ttl_sec=60,
        scope="console",
        owner_session_id="owner-session",
    )
    headers = {
        "X-Internal-Service-Key": gateway_key,
        "X-Console-Expires": str(int(datetime.now(UTC).timestamp()) + 60),
        "X-Role": "l4desk_owner",
        "X-Console-Org": "7",
        "X-Console-User": "owner",
        "X-Console-Session": "owner-session",
    }
    owner_ws = DummyWebSocket(headers, {"lease_id": str(lease.lease_id)})
    await diagnostics_api.diagnostics_ws(
        cast(WebSocket, owner_ws), "SN001", cast(AsyncSession, object())
    )
    assert owner_ws.accepted is True

    no_lease_ws = DummyWebSocket(headers)
    await diagnostics_api.diagnostics_ws(
        cast(WebSocket, no_lease_ws), "SN001", cast(AsyncSession, object())
    )
    assert no_lease_ws.accepted is False
    assert no_lease_ws.close_reason == "lease_required"

    foreign_ws = DummyWebSocket(
        {**headers, "X-Console-Org": "8"}, {"lease_id": str(lease.lease_id)}
    )
    await diagnostics_api.diagnostics_ws(
        cast(WebSocket, foreign_ws), "SN001", cast(AsyncSession, object())
    )
    assert foreign_ws.accepted is False
    assert foreign_ws.close_reason == "lease_inactive"


@pytest.mark.asyncio
async def test_superuser_console_requires_explicit_lease(
    monkeypatch, gateway_key
) -> None:
    async def fake_allowed(*a, **k):
        return True

    monkeypatch.setattr(diagnostics_api, "_is_websocket_device_allowed", fake_allowed)

    async def fake_get_dev(*a, **k):
        return 123

    monkeypatch.setattr(diagnostics_api.DeviceRepo, "get_device_id", fake_get_dev)

    websocket = DummyWebSocket(
        headers={
            "X-Internal-Service-Key": gateway_key,
            "X-Console-Expires": str(int(datetime.now(UTC).timestamp()) + 60),
            "X-Role": "superuser",
            "X-Console-Org": "7",
            "X-Console-User": "su_admin",
            "X-Console-Session": "sess_implicit",
        },
    )

    await diagnostics_api.diagnostics_ws(
        cast(WebSocket, websocket), "SN001", cast(AsyncSession, object())
    )

    assert not websocket.accepted
    assert websocket.close_reason == "lease_required"
    assert await lease_registry.get_active("SN001") is None


@pytest.mark.asyncio
async def test_diagnostics_ws_rejects_foreign_lease(monkeypatch, gateway_key) -> None:
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
            "X-Internal-Service-Key": gateway_key,
            "X-Console-Expires": str(int(datetime.now(UTC).timestamp()) + 60),
            "X-Role": "superuser",
            "X-Console-Org": "7",
            "X-Console-User": "su_admin_2",
            "X-Console-Session": "sess_2",
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
async def test_diagnostics_ws_rejects_active_stream_lease(
    monkeypatch, gateway_key
) -> None:
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
            "X-Internal-Service-Key": gateway_key,
            "X-Console-Expires": str(int(datetime.now(UTC).timestamp()) + 60),
            "X-Role": "superuser",
            "X-Console-Org": "7",
            "X-Console-User": "su_admin",
            "X-Console-Session": "sess_su",
        },
    )

    await diagnostics_api.diagnostics_ws(
        cast(WebSocket, websocket), "SN001", cast(AsyncSession, object())
    )

    assert websocket.accepted is False
    assert websocket.close_code == 4409
    assert websocket.close_reason == "lease_required"

    # Superuser passes stream lease_id -> rejected due to scope mismatch
    ws_stream_id = DummyWebSocket(
        headers={
            "X-Internal-Service-Key": gateway_key,
            "X-Console-Expires": str(int(datetime.now(UTC).timestamp()) + 60),
            "X-Role": "superuser",
            "X-Console-Org": "7",
            "X-Console-User": "operator",
            "X-Console-Session": "sess_op",
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
async def test_diagnostics_ws_disconnect_grace_and_revoke(
    monkeypatch, gateway_key
) -> None:
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
            "X-Internal-Service-Key": gateway_key,
            "X-Console-Expires": str(int(datetime.now(UTC).timestamp()) + 60),
            "X-Role": "superuser",
            "X-Console-Org": "7",
            "X-Console-User": "su_admin",
            "X-Console-Session": "sess_diag",
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
