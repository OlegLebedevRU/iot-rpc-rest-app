from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from core.diagnostics.schemas import DiagnosticSessionKind
from core.diagnostics.sessions import DiagnosticSession, registry as diag_registry
from core.remote_input.leases import LeaseConflictError, LeaseRegistry, mask_user_id
from core.remote_input.schemas import StreamStopCommand


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
        scope="input",
        owner_session_id="sess_1",
    )
    assert lease1.sn == "SN123"
    assert lease1.owner_user_id == "user_1"
    assert lease1.scope == "input"

    active = await registry.get_active("SN123")
    assert active is not None
    assert active.lease_id == lease1.lease_id

    # Second acquire with different user while lease1 is active must raise LeaseConflictError
    with pytest.raises(LeaseConflictError) as exc_info:
        await registry.acquire(
            org_id=1,
            device_id=10,
            sn="SN123",
            owner_user_id="user_2",
            owner_role="user",
            ttl_sec=60,
            scope="input",
            owner_session_id="sess_2",
        )

    err = exc_info.value
    assert err.active_lease.owner_user_id == "user_1"
    assert err.code == "lease_taken"
    assert err.owner_role == "admin"
    assert err.owner_user_id_masked == mask_user_id("user_1")
    assert err.scope == "input"


@pytest.mark.asyncio
async def test_lease_conflict_same_user_different_session():
    registry = LeaseRegistry()

    await registry.acquire(
        org_id=1,
        device_id=10,
        sn="SN123",
        owner_user_id="user_1",
        owner_role="admin",
        ttl_sec=60,
        scope="input",
        owner_session_id="sess_alpha",
    )

    # Same user but different browser session -> LeaseConflictError
    with pytest.raises(LeaseConflictError) as exc_info:
        await registry.acquire(
            org_id=1,
            device_id=10,
            sn="SN123",
            owner_user_id="user_1",
            owner_role="admin",
            ttl_sec=60,
            scope="input",
            owner_session_id="sess_beta",
        )
    assert exc_info.value.code == "lease_taken"


@pytest.mark.asyncio
async def test_lease_idempotent_reacquire_same_user_and_session():
    registry = LeaseRegistry()

    lease1 = await registry.acquire(
        org_id=1,
        device_id=10,
        sn="SN123",
        owner_user_id="user_1",
        owner_role="admin",
        ttl_sec=60,
        scope="input",
        owner_session_id="sess_1",
    )

    # Same user and same session -> returns the exact same lease
    lease2 = await registry.acquire(
        org_id=1,
        device_id=10,
        sn="SN123",
        owner_user_id="user_1",
        owner_role="admin",
        ttl_sec=60,
        scope="input",
        owner_session_id="sess_1",
    )

    assert lease1.lease_id == lease2.lease_id


@pytest.mark.asyncio
async def test_lease_upgrade_scope():
    registry = LeaseRegistry()

    lease = await registry.acquire(
        org_id=1,
        device_id=10,
        sn="SN123",
        owner_user_id="user_1",
        owner_role="admin",
        ttl_sec=60,
        scope="stream",
        owner_session_id="sess_1",
    )
    assert lease.scope == "stream"

    upgraded = await registry.upgrade_scope(lease.lease_id, "input")
    assert upgraded is not None
    assert upgraded.scope == "input"

    fetched = await registry.get(lease.lease_id)
    assert fetched is not None
    assert fetched.scope == "input"


@pytest.mark.asyncio
async def test_console_mutual_exclusion_with_stream_and_input():
    registry = LeaseRegistry()

    # 1. Console blocks stream/input
    console_lease = await registry.acquire(
        org_id=1,
        device_id=10,
        sn="SN_CONSOLE",
        owner_user_id="root",
        owner_role="superuser",
        ttl_sec=60,
        scope="console",
        owner_session_id="sess_c",
    )
    assert console_lease.scope == "console"

    with pytest.raises(LeaseConflictError):
        await registry.acquire(
            org_id=1,
            device_id=10,
            sn="SN_CONSOLE",
            owner_user_id="operator",
            owner_role="user",
            ttl_sec=60,
            scope="input",
            owner_session_id="sess_i",
        )

    await registry.revoke(console_lease.lease_id)

    # 2. Input blocks console
    input_lease = await registry.acquire(
        org_id=1,
        device_id=10,
        sn="SN_CONSOLE",
        owner_user_id="operator",
        owner_role="user",
        ttl_sec=60,
        scope="input",
        owner_session_id="sess_i",
    )

    with pytest.raises(LeaseConflictError):
        await registry.acquire(
            org_id=1,
            device_id=10,
            sn="SN_CONSOLE",
            owner_user_id="root",
            owner_role="superuser",
            ttl_sec=60,
            scope="console",
            owner_session_id="sess_c",
        )

    await registry.revoke(input_lease.lease_id)


@pytest.mark.asyncio
async def test_lease_acquire_race_condition():
    registry = LeaseRegistry()

    async def try_acquire(user_idx: int):
        try:
            return await registry.acquire(
                org_id=1,
                device_id=10,
                sn="SN_RACE",
                owner_user_id=f"user_{user_idx}",
                owner_role="user",
                ttl_sec=60,
                scope="input",
                owner_session_id=f"sess_{user_idx}",
            )
        except LeaseConflictError:
            return None

    results = await asyncio.gather(*(try_acquire(i) for i in range(10)))
    successful = [r for r in results if r is not None]
    assert len(successful) == 1


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
async def test_lease_ws_disconnect_grace_and_cleanup(monkeypatch):
    registry = LeaseRegistry()
    lease = await registry.acquire(
        org_id=1,
        device_id=10,
        sn="SN_GRACE",
        owner_user_id="user_1",
        owner_role="admin",
        ttl_sec=60,
    )

    await registry.mark_ws_connected(lease.lease_id)
    await registry.mark_ws_disconnected(lease.lease_id)

    # Before grace expires (settings grace is 10s), cleanup does NOT revoke
    expired_early = await registry.cleanup_expired()
    assert len(expired_early) == 0
    assert await registry.get_active("SN_GRACE") is not None

    # Wind clock back on disconnected_at by 15s to simulate grace expiry
    lease.ws_disconnected_at = datetime.now(UTC) - timedelta(seconds=15)
    expired_late = await registry.cleanup_expired()
    assert len(expired_late) == 1
    assert expired_late[0][1] == "ws_disconnect_timeout"
    assert await registry.get_active("SN_GRACE") is None


@pytest.mark.asyncio
async def test_lease_revoke_publishes_stream_stop(monkeypatch):
    registry = LeaseRegistry()
    mock_send = AsyncMock()
    monkeypatch.setattr("core.remote_input.leases.send_ctl_command", mock_send)

    lease = await registry.acquire(
        org_id=1,
        device_id=10,
        sn="SN_STREAM",
        owner_user_id="user_1",
        owner_role="admin",
        ttl_sec=60,
        scope="stream",
    )
    stream_id = uuid4()
    lease.stream_instance_id = stream_id

    await registry.revoke(lease.lease_id, reason="released")

    assert mock_send.call_count == 1
    call_args = mock_send.call_args[0]
    assert call_args[0] == "SN_STREAM"
    cmd = call_args[1]
    assert isinstance(cmd, StreamStopCommand)
    assert cmd.stream_instance_id == stream_id


@pytest.mark.asyncio
async def test_lease_revoke_console_closes_diagnostics_sessions():
    registry = LeaseRegistry()

    sess = DiagnosticSession(
        sn="SN_DIAG",
        session_id=uuid4(),
        kind=DiagnosticSessionKind.LIVE_LOG,
        ttl_sec=60,
    )
    await diag_registry.register(sess)
    assert await diag_registry.get("SN_DIAG", sess.session_id) is not None

    lease = await registry.acquire(
        org_id=1,
        device_id=10,
        sn="SN_DIAG",
        owner_user_id="root",
        owner_role="superuser",
        ttl_sec=60,
        scope="console",
    )

    await registry.revoke(lease.lease_id, reason="console_closed")

    # Diagnostics session registry must have been cleared for this SN
    assert await diag_registry.get("SN_DIAG", sess.session_id) is None


@pytest.mark.asyncio
async def test_lease_revoke_by_owner():
    registry = LeaseRegistry()

    l1 = await registry.acquire(
        org_id=1,
        device_id=1,
        sn="SN1",
        owner_user_id="user_multi",
        owner_role="admin",
        ttl_sec=60,
        owner_session_id="sess_A",
    )
    l2 = await registry.acquire(
        org_id=1,
        device_id=2,
        sn="SN2",
        owner_user_id="user_multi",
        owner_role="admin",
        ttl_sec=60,
        owner_session_id="sess_B",
    )
    l3 = await registry.acquire(
        org_id=1,
        device_id=3,
        sn="SN3",
        owner_user_id="user_other",
        owner_role="admin",
        ttl_sec=60,
        owner_session_id="sess_A",
    )

    # 1. Revoke by owner with specific session
    rev1 = await registry.revoke_by_owner("user_multi", "sess_A")
    assert len(rev1) == 1
    assert rev1[0].lease_id == l1.lease_id
    assert not l1.is_active()
    assert l2.is_active()

    # 2. Revoke by owner without session -> revokes remaining leases for user_multi
    rev2 = await registry.revoke_by_owner("user_multi")
    assert len(rev2) == 1
    assert rev2[0].lease_id == l2.lease_id
    assert not l2.is_active()

    # l3 belongs to user_other, remains active
    assert l3.is_active()


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
