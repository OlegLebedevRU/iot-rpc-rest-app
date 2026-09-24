from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from core.remote_input.leases import (
    LeaseConflictError,
    RedisLeaseRegistry,
)
from core.remote_input.presence import RedisPresenceRegistry
from core.remote_input.schemas import (
    CtlPresence,
    DisplayInfo,
    InventoryInfo,
    ScreenInfo,
    StreamInfo,
)


@pytest.mark.asyncio
async def test_redis_lease_acquire_and_touch_atomicity() -> None:
    registry = RedisLeaseRegistry()
    await registry._delete_all_redis_keys()

    sn = "SN_ATOM_01"
    lease = await registry.acquire(
        org_id=1,
        device_id=101,
        sn=sn,
        owner_user_id="user_atom",
        owner_role="operator",
        ttl_sec=60,
        scope="input",
        owner_session_id="sess_atom",
    )
    assert lease.sn == sn
    assert lease.owner_user_id == "user_atom"
    assert lease.scope == "input"

    client = registry._client
    active_id = await client.get(f"l4d:lease:active:{sn}")
    assert active_id == str(lease.lease_id)

    raw_hash = await client.hgetall(f"l4d:lease:{lease.lease_id}")
    assert raw_hash["sn"] == sn
    assert raw_hash["owner_user_id"] == "user_atom"
    assert raw_hash["scope"] == "input"

    hash_ttl = await client.ttl(f"l4d:lease:{lease.lease_id}")
    active_ttl = await client.ttl(f"l4d:lease:active:{sn}")
    assert 50 <= active_ttl <= 60
    assert 80 <= hash_ttl <= 90

    # Touch lease with longer TTL
    touched = await registry.touch(lease.lease_id, ttl_sec=120)
    assert touched is not None
    assert touched.ttl_sec == 120

    active_ttl_after = await client.ttl(f"l4d:lease:active:{sn}")
    hash_ttl_after = await client.ttl(f"l4d:lease:{lease.lease_id}")
    assert 110 <= active_ttl_after <= 120
    assert 140 <= hash_ttl_after <= 150


@pytest.mark.asyncio
async def test_redis_lease_conflict_and_race_prevention() -> None:
    registry = RedisLeaseRegistry()
    await registry._delete_all_redis_keys()

    sn = "SN_RACE_01"
    lease1 = await registry.acquire(
        org_id=1,
        device_id=102,
        sn=sn,
        owner_user_id="user_owner",
        owner_role="operator",
        ttl_sec=60,
        scope="input",
        owner_session_id="sess_owner",
    )

    # Different user -> conflict
    with pytest.raises(LeaseConflictError) as exc_info:
        await registry.acquire(
            org_id=1,
            device_id=102,
            sn=sn,
            owner_user_id="user_intruder",
            owner_role="operator",
            ttl_sec=60,
            scope="input",
            owner_session_id="sess_intruder",
        )
    assert exc_info.value.active_lease.lease_id == lease1.lease_id

    # Same user and session -> idempotent re-acquire / scope upgrade
    upgraded = await registry.acquire(
        org_id=1,
        device_id=102,
        sn=sn,
        owner_user_id="user_owner",
        owner_role="operator",
        ttl_sec=90,
        scope="stream",
        owner_session_id="sess_owner",
    )
    assert upgraded.lease_id == lease1.lease_id
    assert upgraded.scope == "stream"


@pytest.mark.asyncio
async def test_redis_lease_expiration_and_auto_cleanup() -> None:
    registry = RedisLeaseRegistry()
    await registry._delete_all_redis_keys()

    sn = "SN_EXP_01"
    lease = await registry.acquire(
        org_id=1,
        device_id=103,
        sn=sn,
        owner_user_id="user_exp",
        owner_role="operator",
        ttl_sec=1,
        scope="input",
    )

    # Simulate expiration by modifying expires_at in Redis
    past_iso = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    client = registry._client
    await client.hset(f"l4d:lease:{lease.lease_id}", "expires_at", past_iso)
    lease.expires_at = datetime.fromisoformat(past_iso)

    expired = await registry.cleanup_expired()
    assert len(expired) >= 1
    revoked_lease, reason = next(e for e in expired if e[0].sn == sn)
    assert revoked_lease.lease_id == lease.lease_id
    assert reason == "expired"

    active_now = await registry.get_active(sn)
    assert active_now is None


@pytest.mark.asyncio
async def test_redis_presence_and_inventory_recovery_after_restart() -> None:
    # 1. State written by first instance
    presence_reg1 = RedisPresenceRegistry()
    lease_reg1 = RedisLeaseRegistry()
    await presence_reg1._delete_all_redis_keys()
    await lease_reg1._delete_all_redis_keys()

    sn = "SN_RESTART_01"
    p = CtlPresence(
        status="online",
        version="1.8.0",
        capabilities=["quick_actions", "shortcut_action"],
        desktop_available=True,
        session_id=1,
        screen=ScreenInfo(
            virtual_x=0,
            virtual_y=0,
            virtual_width=1920,
            virtual_height=1080,
        ),
        inventory=InventoryInfo(
            displays=[
                DisplayInfo(
                    desktop_id="disp_1",
                    name="Primary Monitor",
                    primary=True,
                    x=0,
                    y=0,
                    width=1920,
                    height=1080,
                    session_id=1,
                    policy="input",
                )
            ],
            cameras=[],
        ),
        stream=StreamInfo(state="stopped"),
        timestamp=datetime.now(UTC).isoformat(),
    )
    await presence_reg1.update(sn, p)

    lease = await lease_reg1.acquire(
        org_id=1,
        device_id=104,
        sn=sn,
        owner_user_id="operator_restart",
        owner_role="operator",
        ttl_sec=100,
        scope="input",
        owner_session_id="sess_restart",
    )

    # 2. Simulate complete restart by creating brand new instances (cold boot)
    presence_reg2 = RedisPresenceRegistry()
    lease_reg2 = RedisLeaseRegistry()

    # Memory cache in instance 2 is empty
    assert sn not in presence_reg2._presence
    assert lease.lease_id not in lease_reg2._leases_by_id

    # 3. Retrieve state from Redis
    status_view = await presence_reg2.get(sn)
    assert status_view.online is True
    assert status_view.version == "1.8.0"
    assert status_view.desktop_available is True
    assert status_view.inventory is not None
    assert len(status_view.inventory.displays) == 1
    assert status_view.inventory.displays[0].desktop_id == "disp_1"

    inventory = await presence_reg2.get_inventory(sn)
    assert len(inventory.displays) == 1
    assert inventory.displays[0].name == "Primary Monitor"

    active_lease = await lease_reg2.get_active(sn)
    assert active_lease is not None
    assert active_lease.lease_id == lease.lease_id
    assert active_lease.owner_user_id == "operator_restart"
    assert active_lease.scope == "input"


@pytest.mark.asyncio
async def test_redis_connection_error_handling() -> None:
    pipe_mock = AsyncMock()
    pipe_mock.__aenter__.side_effect = RedisConnectionError(
        "Connection refused to redis:6379"
    )

    broken_client = AsyncMock()
    broken_client.pipeline = lambda *a, **k: pipe_mock
    broken_client.get.side_effect = RedisConnectionError("Connection refused")
    broken_client.hgetall.side_effect = RedisConnectionError("Connection refused")

    registry = RedisLeaseRegistry()
    registry._leases_by_id.clear()
    registry._active_by_sn.clear()

    # Monkeypatch client property to simulate broken connection
    original_client = registry._client
    type(registry)._client = property(lambda self: broken_client)  # type: ignore

    try:
        # Acquire must raise ConnectionError and NOT create in-memory lease
        with pytest.raises(RedisConnectionError):
            await registry.acquire(
                org_id=1,
                device_id=105,
                sn="SN_ERR_01",
                owner_user_id="user_err",
                owner_role="operator",
                ttl_sec=60,
            )
        assert len(registry._leases_by_id) == 0
        assert len(registry._active_by_sn) == 0

        # Touch must raise ConnectionError
        with pytest.raises(RedisConnectionError):
            await registry.touch(uuid4(), ttl_sec=30)

        # Revoke must raise ConnectionError
        with pytest.raises(RedisConnectionError):
            await registry.revoke(uuid4())

    finally:
        # Restore client
        type(registry)._client = property(lambda self: original_client)  # type: ignore


@pytest.mark.asyncio
async def test_redis_lease_revocation_pubsub() -> None:
    registry = RedisLeaseRegistry()
    await registry._delete_all_redis_keys()

    sn = "SN_PUBSUB_01"
    lease = await registry.acquire(
        org_id=1,
        device_id=106,
        sn=sn,
        owner_user_id="user_pubsub",
        owner_role="operator",
        ttl_sec=60,
    )

    q = await registry.subscribe_revocation(lease.lease_id)
    assert q is not None

    revoked = await registry.revoke(lease.lease_id, reason="admin_forced")
    assert revoked is not None
    assert revoked.revoked_reason == "admin_forced"

    # Queue should receive the revocation event
    reason_received = await asyncio.wait_for(q.get(), timeout=2.0)
    assert reason_received == "admin_forced"
