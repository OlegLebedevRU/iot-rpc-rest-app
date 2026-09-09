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
from core.remote_input.schemas import (
    CtlPresence,
    DisplayInfo,
    InventoryInfo,
    ScreenInfo,
)
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
    async with lease_registry._lock:
        lease_registry._leases_by_id.clear()
        lease_registry._active_by_sn.clear()
        lease_registry._active_ws_leases.clear()
    async with pending_registry._lock:
        pending_registry._pending.clear()
    async with presence_registry._lock:
        presence_registry._presence.clear()
        presence_registry._last_inventory.clear()
        presence_registry._last_stream.clear()


@pytest.mark.asyncio
async def test_rest_auth_and_roles(monkeypatch):
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

        # 4. Missing mandatory X-Session-Id on acquire -> 400
        r4 = await client.post(
            "/api/internal/v1/remote-input/devices/SN123/lease",
            headers={
                "X-Internal-Service-Key": "valid-key",
                "X-Org-Id": "1",
                "X-Role": "admin",
                "X-User-Id": "u1",
            },
        )
        assert r4.status_code == 400

        # 5. Viewer role cannot acquire input lease -> 403 scope_not_allowed
        r5 = await client.post(
            "/api/internal/v1/remote-input/devices/SN123/lease",
            headers={
                "X-Internal-Service-Key": "valid-key",
                "X-Org-Id": "1",
                "X-Role": "viewer",
                "X-User-Id": "u1",
                "X-Session-Id": "s1",
            },
            json={"scope": "input"},
        )
        assert r5.status_code == 403
        assert r5.json()["detail"] == "scope_not_allowed"

        # 6. Viewer role cannot acquire view lease when stream not running -> 409 stream_not_running
        r6 = await client.post(
            "/api/internal/v1/remote-input/devices/SN123/lease",
            headers={
                "X-Internal-Service-Key": "valid-key",
                "X-Org-Id": "1",
                "X-Role": "viewer",
                "X-User-Id": "u1",
                "X-Session-Id": "s1",
            },
            json={"scope": "view"},
        )
        assert r6.status_code == 409
        assert r6.json()["detail"] == "stream_not_running"

        # 7. Non-superuser cannot acquire console lease -> 403
        r7 = await client.post(
            "/api/internal/v1/remote-input/devices/SN123/lease",
            headers={
                "X-Internal-Service-Key": "valid-key",
                "X-Org-Id": "1",
                "X-Role": "admin",
                "X-User-Id": "u1",
                "X-Session-Id": "s1",
            },
            json={"scope": "console"},
        )
        assert r7.status_code == 403
        assert r7.json()["detail"] == "scope_not_allowed"


@pytest.mark.asyncio
async def test_rest_happy_path_and_conflict(monkeypatch):
    async def mock_get_dev(session, sn, org_id):
        return 773 if (org_id == 1 and sn == "SN123") else None

    monkeypatch.setattr("core.crud.device_repo.DeviceRepo.get_device_id", mock_get_dev)
    monkeypatch.setattr(settings.auth, "internal_service_key", "valid-key")

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
            "X-Session-Id": "sess-42",
        }

        # 1. Acquire lease -> 201
        res_lease = await client.post(
            "/api/internal/v1/remote-input/devices/SN123/lease",
            headers=headers,
            json={"scope": "input"},
        )
        assert res_lease.status_code == 201
        lease_data = res_lease.json()
        lease_id = lease_data["lease_id"]
        assert lease_data["sn"] == "SN123"
        assert lease_data["owner_user_id"] == "user-42"
        assert lease_data["scope"] == "input"
        assert lease_data["owner_session_id"] == "sess-42"

        # 2. Second lease on same SN by different user -> 409 LeaseConflictError body
        res_conflict = await client.post(
            "/api/internal/v1/remote-input/devices/SN123/lease",
            headers={
                "X-Internal-Service-Key": "valid-key",
                "X-Org-Id": "1",
                "X-Role": "admin",
                "X-User-Id": "user-other",
                "X-Session-Id": "sess-other",
            },
        )
        assert res_conflict.status_code == 409
        conflict_data = res_conflict.json()["detail"]
        assert conflict_data["code"] == "lease_taken"
        assert conflict_data["owner_role"] == "admin"
        assert "owner_user_id_masked" in conflict_data
        assert conflict_data["scope"] == "input"

        # 3. Upgrade scope to stream -> 200
        res_up = await client.post(
            f"/api/internal/v1/remote-input/lease/{lease_id}/scope",
            headers=headers,
            json={"scope": "stream"},
        )
        assert res_up.status_code == 200
        assert res_up.json()["scope"] == "stream"

        # Upgrade back to input
        await client.post(
            f"/api/internal/v1/remote-input/lease/{lease_id}/scope",
            headers=headers,
            json={"scope": "input"},
        )

        # 4. Get status -> 200
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
        assert status_data["lease"]["scope"] == "input"

        # 5. Keepalive -> 200
        res_ka = await client.post(
            f"/api/internal/v1/remote-input/lease/{lease_id}/keepalive",
            headers=headers,
        )
        assert res_ka.status_code == 200

        # 6. Pointer move -> 202
        with patch(
            "core.remote_input.service.send_ctl_command", new_callable=AsyncMock
        ) as mock_send:
            res_move = await client.post(
                f"/api/internal/v1/remote-input/lease/{lease_id}/pointer/move",
                headers=headers,
                json={"x": 500, "y": 600},
            )
            assert res_move.status_code == 202
            assert res_move.json() == {"accepted": True}
            assert mock_send.call_count == 1

        # 7. Release -> 204
        res_del = await client.delete(
            f"/api/internal/v1/remote-input/lease/{lease_id}",
            headers=headers,
        )
        assert res_del.status_code == 204


@pytest.mark.asyncio
async def test_stream_start_stop_and_timeout(monkeypatch):
    async def mock_get_dev(session, sn, org_id):
        return 773 if (org_id == 1 and sn == "SN123") else None

    monkeypatch.setattr("core.crud.device_repo.DeviceRepo.get_device_id", mock_get_dev)
    monkeypatch.setattr(settings.auth, "internal_service_key", "valid-key")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = {
            "X-Internal-Service-Key": "valid-key",
            "X-Org-Id": "1",
            "X-Role": "admin",
            "X-User-Id": "user-42",
            "X-Session-Id": "sess-42",
        }

        res_lease = await client.post(
            "/api/internal/v1/remote-input/devices/SN123/lease",
            headers=headers,
            json={"scope": "stream"},
        )
        lease_id = res_lease.json()["lease_id"]

        # 1. Stream start success
        with patch(
            "core.remote_input.service.send_ctl_command", new_callable=AsyncMock
        ):

            async def delayed_ack():
                cmd_id = None
                for _ in range(50):
                    await asyncio.sleep(0.02)
                    async with pending_registry._lock:
                        if pending_registry._pending:
                            cmd_id = next(iter(pending_registry._pending.keys()))
                            break
                if cmd_id is None:
                    return
                from core.remote_input.pending import PendingResult

                await pending_registry.resolve(
                    cmd_id,
                    PendingResult(result="started", state="running"),
                )

            asyncio.create_task(delayed_ack())

            res_start = await client.post(
                f"/api/internal/v1/remote-input/lease/{lease_id}/stream/start",
                headers=headers,
                json={"mode": "desktop", "source_id": "disp:1", "profile": "default"},
            )
            assert res_start.status_code == 200
            data = res_start.json()
            assert data["result"] == "started"
            assert data["state"] == "running"
            assert "stream_instance_id" in data

        # 2. Stream stop success
        with patch(
            "core.remote_input.service.send_ctl_command", new_callable=AsyncMock
        ):

            async def delayed_stop_ack():
                cmd_id = None
                for _ in range(50):
                    await asyncio.sleep(0.02)
                    async with pending_registry._lock:
                        if pending_registry._pending:
                            cmd_id = next(iter(pending_registry._pending.keys()))
                            break
                if cmd_id is None:
                    return
                from core.remote_input.pending import PendingResult

                await pending_registry.resolve(
                    cmd_id,
                    PendingResult(result="stopped"),
                )

            asyncio.create_task(delayed_stop_ack())

            res_stop = await client.post(
                f"/api/internal/v1/remote-input/lease/{lease_id}/stream/stop",
                headers=headers,
            )
            assert res_stop.status_code == 200
            assert res_stop.json()["result"] == "stopped"

        # 3. Stream start terminal timeout -> 504
        with patch(
            "core.remote_input.service.send_ctl_command", new_callable=AsyncMock
        ):
            with patch(
                "core.config.settings.remote_input.stream_start_timeout_sec", 0.05
            ):
                res_to = await client.post(
                    f"/api/internal/v1/remote-input/lease/{lease_id}/stream/start",
                    headers=headers,
                    json={"mode": "desktop", "source_id": "disp:1"},
                )
                assert res_to.status_code == 504
                assert res_to.json()["detail"] == "terminal_timeout"


@pytest.mark.asyncio
async def test_key_event_api_and_whitelist(monkeypatch):
    async def mock_get_dev(session, sn, org_id):
        return 773 if (org_id == 1 and sn == "SN123") else None

    monkeypatch.setattr("core.crud.device_repo.DeviceRepo.get_device_id", mock_get_dev)
    monkeypatch.setattr(settings.auth, "internal_service_key", "valid-key")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = {
            "X-Internal-Service-Key": "valid-key",
            "X-Org-Id": "1",
            "X-Role": "admin",
            "X-User-Id": "user-42",
            "X-Session-Id": "sess-42",
        }

        res_lease = await client.post(
            "/api/internal/v1/remote-input/devices/SN123/lease",
            headers=headers,
            json={"scope": "input"},
        )
        lease_id = res_lease.json()["lease_id"]

        # 1. Invalid VK code outside whitelist -> 400
        res_bad_vk = await client.post(
            f"/api/internal/v1/remote-input/lease/{lease_id}/key",
            headers=headers,
            json={"kind": "press", "vk": 0xFF},
        )
        assert res_bad_vk.status_code == 400
        assert res_bad_vk.json()["detail"] == "vk_not_allowed"

        # 2. Valid VK code (0x0D Enter) -> 200
        with patch(
            "core.remote_input.service.send_ctl_command", new_callable=AsyncMock
        ):

            async def delayed_key_ack():
                cmd_id = None
                for _ in range(50):
                    await asyncio.sleep(0.02)
                    async with pending_registry._lock:
                        if pending_registry._pending:
                            cmd_id = next(iter(pending_registry._pending.keys()))
                            break
                if cmd_id is None:
                    return
                from core.remote_input.pending import PendingResult

                await pending_registry.resolve(
                    cmd_id,
                    PendingResult(result="injected", terminal_time_ms=50),
                )

            asyncio.create_task(delayed_key_ack())

            res_key = await client.post(
                f"/api/internal/v1/remote-input/lease/{lease_id}/key",
                headers=headers,
                json={"kind": "press", "vk": 0x0D, "text": "Enter"},
            )
            assert res_key.status_code == 200
            assert res_key.json()["result"] == "injected"


@pytest.mark.asyncio
async def test_inventory_api_and_delete_by_owner(monkeypatch):
    async def mock_get_dev(session, sn, org_id):
        return 773 if (org_id == 1 and sn == "SN123") else None

    monkeypatch.setattr("core.crud.device_repo.DeviceRepo.get_device_id", mock_get_dev)
    monkeypatch.setattr(settings.auth, "internal_service_key", "valid-key")

    await presence_registry.update_inventory(
        "SN123",
        InventoryInfo(
            displays=[
                DisplayInfo(
                    desktop_id="disp:1",
                    name=r"\\.\DISPLAY1",
                    primary=True,
                    width=1920,
                    height=1080,
                )
            ]
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
            "X-Session-Id": "sess-42",
        }

        # 1. Get cached inventory
        res_inv = await client.get(
            "/api/internal/v1/remote-input/devices/SN123/inventory",
            headers=headers,
        )
        assert res_inv.status_code == 200
        inv_data = res_inv.json()
        assert len(inv_data["displays"]) == 1
        assert inv_data["displays"][0]["desktop_id"] == "disp:1"

        # 2. Acquire lease then call delete by owner (logout)
        await client.post(
            "/api/internal/v1/remote-input/devices/SN123/lease",
            headers=headers,
            json={"scope": "input"},
        )
        assert await lease_registry.get_active("SN123") is not None

        res_del_owner = await client.request(
            "DELETE",
            "/api/internal/v1/remote-input/leases/by-owner",
            headers={"X-Internal-Service-Key": "valid-key", "X-Org-Id": "1"},
            json={"user_id": "user-42", "session_id": "sess-42"},
        )
        assert res_del_owner.status_code == 200
        assert res_del_owner.json()["revoked_count"] == 1
        assert await lease_registry.get_active("SN123") is None


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
        scope="input",
        owner_session_id="sess-42",
    )

    # 1. Missing service key -> 4403
    ws_no_key = DummyWS(
        {
            "X-Org-Id": "1",
            "X-Role": "admin",
            "X-User-Id": "user-42",
            "X-Session-Id": "sess-42",
        }
    )
    await remote_input_api.remote_input_ws(cast(any, ws_no_key), lease.lease_id)
    assert ws_no_key.accepted is False
    assert ws_no_key.close_code == 4403

    # 2. Viewer role cannot access input scope WS -> 4403
    ws_viewer = DummyWS(
        {
            "X-Internal-Service-Key": "secret-key",
            "X-Org-Id": "1",
            "X-Role": "viewer",
            "X-User-Id": "user-42",
            "X-Session-Id": "sess-42",
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
            "X-Session-Id": "sess-42",
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
            "X-Session-Id": "sess-42",
        }
    )
    await remote_input_api.remote_input_ws(cast(any, ws_unknown), uuid4())
    assert ws_unknown.accepted is False
    assert ws_unknown.close_code == 4404

    # 5. Happy path connect, receive stream event, and disconnect
    ws_valid = DummyWS(
        {
            "X-Internal-Service-Key": "secret-key",
            "X-Org-Id": "1",
            "X-Role": "admin",
            "X-User-Id": "user-42",
            "X-Session-Id": "sess-42",
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
