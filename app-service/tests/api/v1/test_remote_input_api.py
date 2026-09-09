from __future__ import annotations

import asyncio
from typing import cast
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.datastructures import Headers, QueryParams

from api.internal_v1 import remote_input as remote_input_api
from core.config import settings
from core.remote_input.leases import lease_registry
from core.remote_input.pending import pending_registry
from core.remote_input.presence import presence_registry
from core.remote_input.schemas import CtlPresence, ScreenInfo
from main import main_app as app


class DummyWS:
    def __init__(
        self,
        headers: dict[str, str],
        query_params: dict[str, str] | None = None,
    ) -> None:
        self.headers = Headers(headers)
        self.query_params = QueryParams(query_params or {})
        self.accepted = False
        self.close_code: int | None = None
        self.sent_messages: list[dict] = []
        self.receive_queue: asyncio.Queue[str] = asyncio.Queue()

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000) -> None:
        self.close_code = code

    async def send_json(self, message: dict) -> None:
        self.sent_messages.append(message)

    async def receive_text(self) -> str:
        return await self.receive_queue.get()


@pytest.fixture(autouse=True)
async def cleanup_registries():
    yield
    # Cleanup leases and pending
    async with lease_registry._lock:
        lease_registry._leases_by_id.clear()
        lease_registry._active_by_sn.clear()
        lease_registry._active_ws_leases.clear()
    async with pending_registry._lock:
        pending_registry._pending.clear()
    async with presence_registry._lock:
        presence_registry._presence.clear()


@pytest.mark.asyncio
async def test_rest_auth_and_roles(monkeypatch):
    # Mock DeviceRepo.get_device_id
    async def mock_get_dev(session, sn, org_id):
        if org_id == 1 and sn == "SN123":
            return 773
        return None

    monkeypatch.setattr("core.crud.device_repo.DeviceRepo.get_device_id", mock_get_dev)
    monkeypatch.setattr(settings.auth, "internal_service_key", "valid-key")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 1. Missing service key -> 403
        r1 = await client.get(
            "/api/internal/v1/remote-input/devices/SN123/status",
            headers={"X-Org-Id": "1"},
        )
        assert r1.status_code == 403

        # 2. Invalid service key -> 403
        r2 = await client.get(
            "/api/internal/v1/remote-input/devices/SN123/status",
            headers={"X-Internal-Service-Key": "wrong", "X-Org-Id": "1"},
        )
        assert r2.status_code == 403

        # 3. Cross-tenant (org 2 does not own SN123) -> 403
        r3 = await client.get(
            "/api/internal/v1/remote-input/devices/SN123/status",
            headers={"X-Internal-Service-Key": "valid-key", "X-Org-Id": "2"},
        )
        assert r3.status_code == 403
        assert r3.json()["detail"] == "device not available for organization"

        # 4. Viewer role cannot acquire lease -> 403
        r4 = await client.post(
            "/api/internal/v1/remote-input/devices/SN123/lease",
            headers={
                "X-Internal-Service-Key": "valid-key",
                "X-Org-Id": "1",
                "X-Role": "viewer",
                "X-User-Id": "u1",
            },
        )
        assert r4.status_code == 403
        assert r4.json()["detail"] == "role not allowed for remote input"


@pytest.mark.asyncio
async def test_rest_happy_path_and_conflict(monkeypatch):
    async def mock_get_dev(session, sn, org_id):
        return 773 if (org_id == 1 and sn == "SN123") else None

    monkeypatch.setattr("core.crud.device_repo.DeviceRepo.get_device_id", mock_get_dev)
    monkeypatch.setattr(settings.auth, "internal_service_key", "valid-key")

    # Set presence
    await presence_registry.update(
        "SN123",
        CtlPresence(
            agent="l4desk",
            status="online",
            desktop_available=True,
            screen=ScreenInfo(
                virtual_x=0, virtual_y=0, virtual_width=1920, virtual_height=1080
            ),
            timestamp="2026-09-09T00:00:00Z",
        ),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = {
            "X-Internal-Service-Key": "valid-key",
            "X-Org-Id": "1",
            "X-Role": "admin",
            "X-User-Id": "user-42",
        }

        # 1. Acquire lease -> 201
        res_lease = await client.post(
            "/api/internal/v1/remote-input/devices/SN123/lease",
            headers=headers,
            json={"owner_user_id": "user-42", "owner_role": "admin"},
        )
        assert res_lease.status_code == 201
        lease_data = res_lease.json()
        lease_id = lease_data["lease_id"]
        assert lease_data["sn"] == "SN123"
        assert lease_data["owner_user_id"] == "user-42"
        assert (
            lease_data["ws_path"]
            == f"/api/internal/v1/remote-input/ws/lease/{lease_id}"
        )

        # 2. Second lease on same SN -> 409 Conflict
        res_conflict = await client.post(
            "/api/internal/v1/remote-input/devices/SN123/lease",
            headers={
                "X-Internal-Service-Key": "valid-key",
                "X-Org-Id": "1",
                "X-Role": "admin",
                "X-User-Id": "user-other",
            },
        )
        assert res_conflict.status_code == 409
        conflict_data = res_conflict.json()["detail"]
        assert conflict_data["detail"] == "lease busy"
        assert conflict_data["owner_user_id"] == "user-42"

        # 3. Get status -> 200
        res_status = await client.get(
            "/api/internal/v1/remote-input/devices/SN123/status",
            headers=headers,
        )
        assert res_status.status_code == 200
        status_data = res_status.json()
        assert status_data["agent"]["online"] is True
        assert status_data["agent"]["desktop_available"] is True
        assert status_data["lease"]["active"] is True
        assert status_data["lease"]["owner_user_id"] == "user-42"

        # 4. Keepalive -> 200
        res_ka = await client.post(
            f"/api/internal/v1/remote-input/lease/{lease_id}/keepalive",
            headers=headers,
        )
        assert res_ka.status_code == 200

        # 5. Pointer move -> 202
        with patch(
            "core.remote_input.service.send_ctl_command", new_callable=AsyncMock
        ) as mock_send:
            res_move = await client.post(
                f"/api/internal/v1/remote-input/lease/{lease_id}/pointer-move",
                headers=headers,
                json={"x": 500, "y": 600},
            )
            assert res_move.status_code == 202
            assert res_move.json() == {"accepted": True}
            assert mock_send.call_count == 1

        # 6. Release -> 204
        res_del = await client.delete(
            f"/api/internal/v1/remote-input/lease/{lease_id}",
            headers=headers,
        )
        assert res_del.status_code == 204

        # 7. Post release, status shows lease active=False
        res_status2 = await client.get(
            "/api/internal/v1/remote-input/devices/SN123/status",
            headers=headers,
        )
        assert res_status2.json()["lease"]["active"] is False


@pytest.mark.asyncio
async def test_websocket_lifecycle(monkeypatch):
    monkeypatch.setattr(settings.auth, "internal_service_key", "secret-key")

    lease = await lease_registry.acquire(
        org_id=1,
        device_id=773,
        sn="SN123",
        owner_user_id="user-42",
        owner_role="admin",
        ttl_sec=60,
    )

    # 1. Missing service key -> 4403
    ws_no_key = DummyWS({"X-Org-Id": "1", "X-Role": "admin", "X-User-Id": "user-42"})
    await remote_input_api.remote_input_ws(cast(any, ws_no_key), lease.lease_id)
    assert ws_no_key.accepted is False
    assert ws_no_key.close_code == 4403

    # 2. Viewer role -> 4403
    ws_viewer = DummyWS(
        {
            "X-Internal-Service-Key": "secret-key",
            "X-Org-Id": "1",
            "X-Role": "viewer",
            "X-User-Id": "user-42",
        }
    )
    await remote_input_api.remote_input_ws(cast(any, ws_viewer), lease.lease_id)
    assert ws_viewer.accepted is False
    assert ws_viewer.close_code == 4403

    # 3. Cross-tenant org_id mismatch -> 4403
    ws_cross = DummyWS(
        {
            "X-Internal-Service-Key": "secret-key",
            "X-Org-Id": "99",
            "X-Role": "user",
            "X-User-Id": "user-42",
        }
    )
    await remote_input_api.remote_input_ws(cast(any, ws_cross), lease.lease_id)
    assert ws_cross.accepted is False
    assert ws_cross.close_code == 4403

    # 4. Unknown lease -> 4404
    ws_unknown = DummyWS(
        {
            "X-Internal-Service-Key": "secret-key",
            "X-Org-Id": "1",
            "X-Role": "admin",
            "X-User-Id": "user-42",
        }
    )
    await remote_input_api.remote_input_ws(cast(any, ws_unknown), uuid4())
    assert ws_unknown.accepted is False
    assert ws_unknown.close_code == 4404

    # 5. Happy path connect & disconnect
    ws_valid = DummyWS(
        {
            "X-Internal-Service-Key": "secret-key",
            "X-Org-Id": "1",
            "X-Role": "admin",
            "X-User-Id": "user-42",
        }
    )

    # Prepare to send release command to terminate loop
    await ws_valid.receive_queue.put('{"type":"release"}')

    await remote_input_api.remote_input_ws(cast(any, ws_valid), lease.lease_id)
    assert ws_valid.accepted is True
    # Initial hello and presence sent
    sent_types = [m.get("type") for m in ws_valid.sent_messages]
    assert "hello" in sent_types
    assert "presence" in sent_types

    # Lease was released on disconnect
    active = await lease_registry.get_active("SN123")
    assert active is None
