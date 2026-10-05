from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from core.remote_input.leases import (
    LeaseConflictError,
    LeaseRegistry,
    RedisLeaseRegistry,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("registry_type", [LeaseRegistry, RedisLeaseRegistry])
@pytest.mark.parametrize("other", ["console", "view", "stream", "input"])
async def test_files_and_other_modes_exclude_even_the_same_owner(registry_type, other):
    registry = registry_type()
    sn = f"fixture-{uuid4()}"
    lease = await registry.acquire(
        7, 10, sn, "fixture", "user", 60, scope="files", owner_session_id="same-tab"
    )
    with pytest.raises(LeaseConflictError):
        await registry.acquire(
            7, 10, sn, "fixture", "user", 60, scope=other, owner_session_id="same-tab"
        )
    with pytest.raises(LeaseConflictError):
        await registry.upgrade_scope(lease.lease_id, other)
    assert (await registry.get(lease.lease_id)).scope == "files"


@pytest.mark.anyio
@pytest.mark.parametrize("registry_type", [LeaseRegistry, RedisLeaseRegistry])
async def test_release_cannot_be_revived_and_keeps_drain_guard(registry_type):
    registry = registry_type()
    sn = f"fixture-{uuid4()}"
    lease = await registry.acquire(
        7, 10, sn, "fixture", "user", 90, scope="files", owner_session_id="tab"
    )
    await registry.revoke(lease.lease_id)
    assert await registry.touch(lease.lease_id, 60) is None
    with pytest.raises(LeaseConflictError):
        await registry.acquire(
            7, 10, sn, "fixture", "user", 60, scope="files", owner_session_id="tab"
        )
    with pytest.raises(LeaseConflictError):
        await registry.acquire(
            7,
            10,
            sn,
            "different",
            "admin",
            60,
            scope="console",
            owner_session_id="other",
        )
    if isinstance(registry, RedisLeaseRegistry):
        assert await registry._client.ttl(f"l4d:lease:active:{sn}") >= 90
        assert await registry._client.ttl(f"l4d:lease:{lease.lease_id}") >= 90


@pytest.mark.anyio
async def test_registry_cache_cannot_overwrite_revocation_from_another_worker():
    first, second = RedisLeaseRegistry(), RedisLeaseRegistry()
    lease = await first.acquire(
        7,
        10,
        f"fixture-{uuid4()}",
        "fixture",
        "user",
        60,
        scope="files",
        owner_session_id="tab",
    )
    await second.get(lease.lease_id)
    await first.revoke(lease.lease_id)
    observed = await second.get(lease.lease_id)
    assert observed.revoked_reason == "released"
    assert await second.touch(lease.lease_id, 60) is None


@pytest.mark.anyio
async def test_files_guard_eventually_allows_new_session():
    registry = LeaseRegistry()
    lease = await registry.acquire(
        7,
        10,
        "fixture-expired",
        "fixture",
        "user",
        60,
        scope="files",
        owner_session_id="tab",
    )
    await registry.revoke(lease.lease_id)
    lease.expires_at = datetime.now(UTC) - timedelta(seconds=6)
    new = await registry.acquire(
        7, 10, lease.sn, "fixture", "user", 60, scope="console", owner_session_id="tab"
    )
    assert new.lease_id != lease.lease_id


def test_file_manager_signal_requires_exact_operation_shape():
    from api.internal_v1.file_manager import Signal
    from pydantic import ValidationError

    for action in ("start", "renew", "stop"):
        Signal(action=action)
        with pytest.raises(ValidationError):
            Signal(action=action, operation_id=uuid4())
    for action in ("transfer", "cancel"):
        Signal(action=action, operation_id=uuid4())
        with pytest.raises(ValidationError):
            Signal(action=action)
