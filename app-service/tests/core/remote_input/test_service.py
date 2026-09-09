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
    return srv, leases, pending


@pytest.mark.asyncio
async def test_mouse_click_injected(service_env):
    srv, leases, pending = service_env

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
    srv, leases, pending = service_env

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
    srv, leases, pending = service_env

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
    srv, leases, _ = service_env

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
