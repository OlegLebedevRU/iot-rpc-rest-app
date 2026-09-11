from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from core.remote_input.leases import LeaseRegistry
from core.remote_input.pending import PendingCommandRegistry, PendingResult
from core.remote_input.presence import PresenceRegistry
from core.remote_input.rate_limit import RateLimiter
from core.remote_input.schemas import DisplayInfo, InventoryInfo
from core.remote_input.service import RemoteInputService


@pytest.fixture
def service_env():
    leases = LeaseRegistry()
    presence = PresenceRegistry()
    pending = PendingCommandRegistry()
    limiter = RateLimiter()
    srv = RemoteInputService(
        leases=leases,
        presence=presence,
        pending=pending,
        limiter=limiter,
    )
    return srv, leases, pending, presence


@pytest.mark.asyncio
async def test_mouse_click_injected(service_env):
    srv, leases, pending, _ = service_env

    lease = await leases.acquire(
        org_id=1,
        device_id=10,
        sn="SN123",
        owner_user_id="user1",
        owner_role="admin",
        ttl_sec=60,
    )

    with patch(
        "core.remote_input.service.send_ctl_command", new_callable=AsyncMock
    ) as mock_send:
        # Simulate terminal sending ACK while click is in flight
        async def delayed_ack():
            await asyncio.sleep(0.01)
            # Find registered command in pending
            async with pending._lock:
                cmd_id = next(iter(pending._pending.keys()))
            await pending.resolve(
                cmd_id,
                PendingResult(result="injected", terminal_time_ms=123),
            )

        asyncio.create_task(delayed_ack())

        res = await srv.mouse_click(
            lease_id=lease.lease_id,
            org_id=1,
            x=100,
            y=200,
            button="left",
            client_ref="ref-1",
        )

        assert res.result == "injected"
        assert res.client_ref == "ref-1"
        assert mock_send.call_count == 1
        call_args = mock_send.call_args[0]
        assert call_args[0] == "SN123"
        assert call_args[1].button == "left"


@pytest.mark.asyncio
async def test_mouse_click_nack(service_env):
    srv, leases, pending, _ = service_env

    lease = await leases.acquire(
        org_id=1,
        device_id=10,
        sn="SN123",
        owner_user_id="user1",
        owner_role="admin",
        ttl_sec=60,
    )

    with patch("core.remote_input.service.send_ctl_command", new_callable=AsyncMock):

        async def delayed_nack():
            await asyncio.sleep(0.01)
            async with pending._lock:
                cmd_id = next(iter(pending._pending.keys()))
            await pending.resolve(
                cmd_id,
                PendingResult(
                    result="nack",
                    code="interactive_desktop_unavailable",
                    message="Desktop locked",
                ),
            )

        asyncio.create_task(delayed_nack())

        res = await srv.mouse_click(
            lease_id=lease.lease_id,
            org_id=1,
            x=100,
            y=200,
            button="left",
        )

        assert res.result == "nack"
        assert res.code == "interactive_desktop_unavailable"
        assert res.message == "Desktop locked"


@pytest.mark.asyncio
async def test_mouse_click_timeout_unconfirmed_no_retry(service_env):
    srv, leases, pending, _ = service_env

    lease = await leases.acquire(
        org_id=1,
        device_id=10,
        sn="SN123",
        owner_user_id="user1",
        owner_role="admin",
        ttl_sec=60,
    )

    with patch(
        "core.remote_input.service.send_ctl_command", new_callable=AsyncMock
    ) as mock_send:
        # Patch timeout to be fast for test
        with patch("core.config.settings.remote_input.click_ack_timeout_ms", 20):
            res = await srv.mouse_click(
                lease_id=lease.lease_id,
                org_id=1,
                x=100,
                y=200,
            )

            assert res.result == "unconfirmed"
            assert res.code == "ack_timeout"
            # Exactly one attempt, no automatic retry!
            assert mock_send.call_count == 1


@pytest.mark.asyncio
async def test_pointer_move_and_rate_limit(service_env):
    srv, leases, _, _ = service_env

    lease = await leases.acquire(
        org_id=1,
        device_id=10,
        sn="SN123",
        owner_user_id="user1",
        owner_role="admin",
        ttl_sec=60,
    )

    with patch(
        "core.remote_input.service.send_ctl_command", new_callable=AsyncMock
    ) as mock_send:
        res = await srv.pointer_move(lease_id=lease.lease_id, org_id=1, x=10, y=20)
        assert res == {"accepted": True}
        assert mock_send.call_count == 1

        # Exhaust rate limit
        with patch("core.config.settings.remote_input.move_rate_per_sec", 1):
            # First one passes or uses up bucket
            srv.limiter._buckets.clear()
            await srv.pointer_move(lease_id=lease.lease_id, org_id=1, x=10, y=20)
            # Immediate second should be rate limited
            with pytest.raises(HTTPException) as exc_info:
                await srv.pointer_move(lease_id=lease.lease_id, org_id=1, x=10, y=20)
            assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_stream_start_and_stop_service(service_env):
    srv, leases, pending, presence = service_env

    await presence.update_inventory(
        "SN123",
        InventoryInfo(
            displays=[
                DisplayInfo(
                    desktop_id="disp:1",
                    name=r"\\.\DISPLAY1",
                    primary=True,
                    width=1920,
                    height=1080,
                    session_id=42,
                )
            ]
        ),
    )

    lease = await leases.acquire(
        org_id=1,
        device_id=10,
        sn="SN123",
        owner_user_id="user1",
        owner_role="admin",
        ttl_sec=60,
        scope="stream",
        owner_session_id="sess_1",
    )

    with patch("core.remote_input.service.send_ctl_command", new_callable=AsyncMock):

        async def delayed_start_ack():
            await asyncio.sleep(0.01)
            async with pending._lock:
                cmd_id = next(iter(pending._pending.keys()))
            await pending.resolve(
                cmd_id,
                PendingResult(result="started", state="running"),
            )

        asyncio.create_task(delayed_start_ack())

        resp = await srv.stream_start(
            lease_id=lease.lease_id,
            org_id=1,
            mode="desktop",
            source_id="disp:1",
            caller_user_id="user1",
            caller_session_id="sess_1",
        )

        assert resp.result == "started"
        assert resp.state == "running"
        assert lease.stream_instance_id == resp.stream_instance_id
        assert lease.stream_mode == "desktop"
        assert lease.selected_desktop_id == "disp:1"
        assert lease.selected_session_id == 42

    with patch("core.remote_input.service.send_ctl_command", new_callable=AsyncMock):

        async def delayed_stop_ack():
            await asyncio.sleep(0.01)
            async with pending._lock:
                cmd_id = next(iter(pending._pending.keys()))
            await pending.resolve(
                cmd_id,
                PendingResult(result="stopped"),
            )

        asyncio.create_task(delayed_stop_ack())

        stop_resp = await srv.stream_stop(
            lease_id=lease.lease_id,
            org_id=1,
            caller_user_id="user1",
            caller_session_id="sess_1",
        )

        assert stop_resp.result == "stopped"
        assert lease.stream_instance_id is None
        assert lease.stream_mode is None


@pytest.mark.asyncio
async def test_input_forbidden_in_camera_mode(service_env):
    srv, leases, _, _ = service_env

    lease = await leases.acquire(
        org_id=1,
        device_id=10,
        sn="SN123",
        owner_user_id="user1",
        owner_role="admin",
        ttl_sec=60,
        scope="input",
        owner_session_id="sess_1",
    )
    # Put stream mode into usb-camera
    lease.stream_mode = "usb-camera"

    # Mouse click forbidden
    with pytest.raises(HTTPException) as exc_click:
        await srv.mouse_click(
            lease_id=lease.lease_id,
            org_id=1,
            x=10,
            y=10,
            caller_user_id="user1",
            caller_session_id="sess_1",
        )
    assert exc_click.value.status_code == 409
    assert exc_click.value.detail == "input_not_allowed_in_camera_mode"

    # Pointer move forbidden
    with pytest.raises(HTTPException) as exc_move:
        await srv.pointer_move(
            lease_id=lease.lease_id,
            org_id=1,
            x=10,
            y=10,
            caller_user_id="user1",
            caller_session_id="sess_1",
        )
    assert exc_move.value.status_code == 409
    assert exc_move.value.detail == "input_not_allowed_in_camera_mode"

    # Key event forbidden
    with pytest.raises(HTTPException) as exc_key:
        await srv.key_event(
            lease_id=lease.lease_id,
            org_id=1,
            kind="press",
            vk=0x0D,
            caller_user_id="user1",
            caller_session_id="sess_1",
        )
    assert exc_key.value.status_code == 409
    assert exc_key.value.detail == "input_not_allowed_in_camera_mode"


@pytest.mark.asyncio
async def test_desktop_and_stream_mismatch(service_env):
    srv, leases, _, _ = service_env

    sid = uuid4()
    lease = await leases.acquire(
        org_id=1,
        device_id=10,
        sn="SN123",
        owner_user_id="user1",
        owner_role="admin",
        ttl_sec=60,
        scope="input",
        owner_session_id="sess_1",
    )
    lease.stream_mode = "desktop"
    lease.selected_desktop_id = "disp:primary"
    lease.stream_instance_id = sid

    # Desktop mismatch
    with pytest.raises(HTTPException) as exc_disp:
        await srv.pointer_move(
            lease_id=lease.lease_id,
            org_id=1,
            x=10,
            y=10,
            desktop_id="disp:other",
            caller_user_id="user1",
            caller_session_id="sess_1",
        )
    assert exc_disp.value.status_code == 409
    assert exc_disp.value.detail == "desktop_mismatch"

    # Stream instance mismatch
    with pytest.raises(HTTPException) as exc_stream:
        await srv.pointer_move(
            lease_id=lease.lease_id,
            org_id=1,
            x=10,
            y=10,
            stream_instance_id=uuid4(),
            caller_user_id="user1",
            caller_session_id="sess_1",
        )
    assert exc_stream.value.status_code == 409
    assert exc_stream.value.detail == "stream_mismatch"


@pytest.mark.asyncio
async def test_publisher_send_ctl_command():
    from core.remote_input.publisher import send_ctl_command
    from core.remote_input.schemas import MouseClickCommand

    cid = uuid4()
    lid = uuid4()
    cmd = MouseClickCommand(
        command_id=cid,
        lease_id=lid,
        sn="SN9999",
        x=1000,
        y=2000,
        button="left",
        issued_at_ms=1000,
        expires_at_ms=6000,
    )

    with patch(
        "core.remote_input.publisher.topic_publisher.publish", new_callable=AsyncMock
    ) as mock_pub:
        await send_ctl_command("SN9999", cmd, ttl_ms=5000)
        assert mock_pub.call_count == 1
        kwargs = mock_pub.call_args.kwargs
        assert kwargs["routing_key"] == "srv.SN9999.ctl"
        assert kwargs["correlation_id"] == cid
        assert kwargs["expiration"] == 5000
        assert kwargs["headers"] == {
            "correlationData": str(cid),
            "ctl_type": "mouse_click",
        }
        # Verify no retain is passed or requested
        assert "retain" not in kwargs or kwargs["retain"] is False


@pytest.mark.asyncio
async def test_stream_start_idempotent_when_already_running(service_env):
    srv, leases, pending, presence = service_env

    await presence.update_inventory(
        "SN123",
        InventoryInfo(
            displays=[
                DisplayInfo(
                    desktop_id="disp:1",
                    name=r"\\.\DISPLAY1",
                    primary=True,
                    width=1920,
                    height=1080,
                    session_id=42,
                )
            ]
        ),
    )

    lease = await leases.acquire(
        org_id=1,
        device_id=10,
        sn="SN123",
        owner_user_id="user1",
        owner_role="admin",
        ttl_sec=60,
        scope="stream",
        owner_session_id="sess_1",
    )

    # 1. Первый вызов stream_start запускает стрим и сохраняет stream_instance_id
    with patch(
        "core.remote_input.service.send_ctl_command", new_callable=AsyncMock
    ) as mock_send:

        async def delayed_start_ack():
            await asyncio.sleep(0.01)
            async with pending._lock:
                cmd_id = next(iter(pending._pending.keys()))
            await pending.resolve(
                cmd_id,
                PendingResult(result="started", state="running"),
            )

        asyncio.create_task(delayed_start_ack())

        resp1 = await srv.stream_start(
            lease_id=lease.lease_id,
            org_id=1,
            mode="desktop",
            source_id="disp:1",
            caller_user_id="user1",
            caller_session_id="sess_1",
        )

        assert resp1.result == "started"
        assert resp1.state == "running"
        assert lease.stream_instance_id == resp1.stream_instance_id
        assert lease.stream_mode == "desktop"
        assert lease.selected_desktop_id == "disp:1"
        assert mock_send.call_count == 1

    # 2. Второй вызов с теми же параметрами возвращает result="already_running"
    #    и тот же stream_instance_id без отправки повторной команды в MQTT
    with patch(
        "core.remote_input.service.send_ctl_command", new_callable=AsyncMock
    ) as mock_send_second:
        resp2 = await srv.stream_start(
            lease_id=lease.lease_id,
            org_id=1,
            mode="desktop",
            source_id="disp:1",
            caller_user_id="user1",
            caller_session_id="sess_1",
        )

        assert resp2.result == "already_running"
        assert resp2.state == "running"
        assert resp2.stream_instance_id == resp1.stream_instance_id
        assert lease.stream_instance_id == resp1.stream_instance_id
        assert mock_send_second.call_count == 0


@pytest.mark.asyncio
async def test_stream_stop_idempotent_when_already_stopped(service_env):
    srv, leases, _, _ = service_env

    lease = await leases.acquire(
        org_id=1,
        device_id=10,
        sn="SN123",
        owner_user_id="user1",
        owner_role="admin",
        ttl_sec=60,
        scope="stream",
        owner_session_id="sess_1",
    )
    assert lease.stream_instance_id is None

    with patch(
        "core.remote_input.service.send_ctl_command", new_callable=AsyncMock
    ) as mock_send:
        stop_resp = await srv.stream_stop(
            lease_id=lease.lease_id,
            org_id=1,
            caller_user_id="user1",
            caller_session_id="sess_1",
        )

        assert stop_resp.result == "already_stopped"
        assert stop_resp.state == "stopped"
        assert lease.stream_instance_id is None
        assert mock_send.call_count == 0


@pytest.mark.asyncio
async def test_stream_event_clears_lease_stream_instance(service_env):
    from core.remote_input.mqtt_bridge import handle_device_ctl_message

    _, leases, pending, presence = service_env

    sid = uuid4()
    lease = await leases.acquire(
        org_id=1,
        device_id=10,
        sn="SN123",
        owner_user_id="user1",
        owner_role="admin",
        ttl_sec=60,
        scope="stream",
        owner_session_id="sess_1",
    )
    lease.stream_instance_id = sid
    lease.stream_mode = "desktop"
    lease.selected_desktop_id = "disp:1"

    # Terminal sends stream_event with state="failed"
    event_payload = {
        "v": 1,
        "type": "stream_event",
        "stream_instance_id": str(sid),
        "state": "failed",
        "reason": "encoder_error",
        "timestamp": "2026-09-11T00:00:00Z",
    }

    handled = await handle_device_ctl_message(
        routing_key="dev.SN123.ctl",
        payload=event_payload,
        p_registry=presence,
        cmd_registry=pending,
        l_registry=leases,
    )

    assert handled is True
    # lease stream fields must be cleared
    assert lease.stream_instance_id is None
    assert lease.stream_mode is None
    assert lease.selected_desktop_id is None

    # presence must also reflect failed stream
    stream_info = await presence.get_stream("SN123")
    assert stream_info.state == "failed"
    assert stream_info.reason == "encoder_error"


@pytest.mark.asyncio
async def test_stream_start_sequential_switch(service_env):
    srv, leases, pending, presence = service_env

    await presence.update_inventory(
        "SN123",
        InventoryInfo(
            displays=[
                DisplayInfo(
                    desktop_id="disp:1",
                    name=r"\\.\DISPLAY1",
                    primary=True,
                    width=1920,
                    height=1080,
                    session_id=42,
                ),
                DisplayInfo(
                    desktop_id="disp:2",
                    name=r"\\.\DISPLAY2",
                    primary=False,
                    width=1920,
                    height=1080,
                    session_id=42,
                ),
            ]
        ),
    )

    lease = await leases.acquire(
        org_id=1,
        device_id=10,
        sn="SN123",
        owner_user_id="user1",
        owner_role="admin",
        ttl_sec=60,
        scope="stream",
        owner_session_id="sess_1",
    )

    # 1. Start on disp:1
    with patch("core.remote_input.service.send_ctl_command", new_callable=AsyncMock):

        async def ack_start():
            await asyncio.sleep(0.01)
            async with pending._lock:
                cmd_id = next(iter(pending._pending.keys()))
            await pending.resolve(
                cmd_id,
                PendingResult(result="started", state="running"),
            )

        asyncio.create_task(ack_start())

        resp1 = await srv.stream_start(
            lease_id=lease.lease_id,
            org_id=1,
            mode="desktop",
            source_id="disp:1",
            caller_user_id="user1",
            caller_session_id="sess_1",
        )
        assert resp1.result == "started"

    # 2. Sequential switch to disp:2 should send new command to terminal
    with patch(
        "core.remote_input.service.send_ctl_command", new_callable=AsyncMock
    ) as mock_send_switch:

        async def ack_switch():
            await asyncio.sleep(0.01)
            async with pending._lock:
                cmd_id = next(iter(pending._pending.keys()))
            await pending.resolve(
                cmd_id,
                PendingResult(result="switched", state="running"),
            )

        asyncio.create_task(ack_switch())

        resp2 = await srv.stream_start(
            lease_id=lease.lease_id,
            org_id=1,
            mode="desktop",
            source_id="disp:2",
            caller_user_id="user1",
            caller_session_id="sess_1",
        )

        assert resp2.result == "switched"
        assert resp2.stream_instance_id != resp1.stream_instance_id
        assert lease.stream_instance_id == resp2.stream_instance_id
        assert lease.selected_desktop_id == "disp:2"
        assert mock_send_switch.call_count == 1
