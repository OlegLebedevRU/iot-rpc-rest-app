from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from core.remote_input.leases import LeaseConflictError, LeaseRegistry


@pytest.mark.asyncio
async def test_lease_single_active_and_conflict():
    registry = LeaseRegistry()

    lease1 = await registry.acquire(
        org_id=1,
        device_id=10,
        sn="SN123",
        owner_user_id="user_1",
        owner_role="admin",
        ttl_sec=60,
    )
    assert lease1.sn == "SN123"
    assert lease1.owner_user_id == "user_1"

    active = await registry.get_active("SN123")
    assert active is not None
    assert active.lease_id == lease1.lease_id

    # Second acquire while lease1 is active must raise LeaseConflictError
    with pytest.raises(LeaseConflictError) as exc_info:
        await registry.acquire(
            org_id=1,
            device_id=10,
            sn="SN123",
            owner_user_id="user_2",
            owner_role="user",
            ttl_sec=60,
        )

    assert exc_info.value.active_lease.owner_user_id == "user_1"


@pytest.mark.asyncio
async def test_lease_touch_and_revoke():
    registry = LeaseRegistry()
    lease = await registry.acquire(
        org_id=1,
        device_id=10,
        sn="SN123",
        owner_user_id="user_1",
        owner_role="admin",
        ttl_sec=10,
    )

    old_expires_at = lease.expires_at
    await asyncio.sleep(0.01)
    touched = await registry.touch(lease.lease_id, ttl_sec=60)
    assert touched is not None
    assert touched.expires_at > old_expires_at

    revoked = await registry.revoke(lease.lease_id, reason="released")
    assert revoked is not None
    assert revoked.revoked_reason == "released"
    assert not revoked.is_active()

    active = await registry.get_active("SN123")
    assert active is None


@pytest.mark.asyncio
async def test_lease_cleanup_expired():
    registry = LeaseRegistry()
    lease = await registry.acquire(
        org_id=1,
        device_id=10,
        sn="SN123",
        owner_user_id="user_1",
        owner_role="admin",
        ttl_sec=1,
    )

    # Force expiration by adjusting expires_at backwards
    lease.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    expired_list = await registry.cleanup_expired()
    assert len(expired_list) == 1
    exp_lease, reason = expired_list[0]
    assert exp_lease.lease_id == lease.lease_id
    assert reason == "expired"

    assert await registry.get_active("SN123") is None


@pytest.mark.asyncio
async def test_lease_mark_ws_connected_prevent_duplicate():
    registry = LeaseRegistry()
    lease = await registry.acquire(
        org_id=1,
        device_id=10,
        sn="SN123",
        owner_user_id="user_1",
        owner_role="admin",
        ttl_sec=60,
    )

    conn1 = await registry.mark_ws_connected(lease.lease_id)
    assert conn1 is True

    # Second connection to same lease rejected
    conn2 = await registry.mark_ws_connected(lease.lease_id)
    assert conn2 is False

    await registry.mark_ws_disconnected(lease.lease_id)
    conn3 = await registry.mark_ws_connected(lease.lease_id)
    assert conn3 is True
