from datetime import timedelta
from uuid import uuid4
from unittest.mock import AsyncMock, patch
import json
import pytest
from core.remote_input.leases import (
    LeaseRegistry,
    RedisLeaseRegistry,
    LeaseConflictError,
)
from core import file_manager_navigation as fm
from core.redis_helper import redis_helper


@pytest.mark.anyio
@pytest.mark.parametrize("registry_type", [LeaseRegistry, RedisLeaseRegistry])
async def test_repeated_files_acquire_is_not_an_implicit_renew(registry_type):
    registry = registry_type()
    sn = f"fixture-{uuid4()}"
    lease = await registry.acquire(
        7, 10, sn, "user", "user", 60, scope="files", owner_session_id="tab"
    )
    expiry = lease.expires_at
    with pytest.raises(LeaseConflictError):
        await registry.acquire(
            7, 10, sn, "user", "user", 90, scope="files", owner_session_id="tab"
        )
    assert (await registry.get(lease.lease_id)).expires_at == expiry


@pytest.mark.anyio
async def test_response_is_correlated_across_workers_and_wrong_sn_is_ignored():
    registry = RedisLeaseRegistry()
    lease = await registry.acquire(
        7,
        10,
        f"fixture-{uuid4()}",
        "user",
        "user",
        60,
        scope="files",
        owner_session_id="tab",
    )

    async def publish(**kwargs):
        command = kwargs["message"]
        assert kwargs["routing_key"].endswith(".fmc")
        assert kwargs["expiration"] == timedelta(seconds=7)
        response = {
            "v": 2,
            "command_id": command["command_id"],
            "lease_id": str(lease.lease_id),
            "state": "completed",
            "entries": [],
        }
        pending = f"l4fm:pending:{command['command_id']}"
        assert await redis_helper.get_client().get(pending)
        await fm.accept_result("wrong-sn", json.dumps(response).encode())
        assert await redis_helper.get_client().get(pending + ":result") is None
        await fm.accept_result(lease.sn, json.dumps(response).encode())
        await fm.accept_result(lease.sn, json.dumps(response).encode())

    with (
        patch.object(fm.topic_publisher, "publish", publish),
        patch.object(fm, "lease_registry", registry),
    ):
        result = await fm.navigate(lease, fm.Navigation(path="C:\\"))
    assert result["state"] == "completed"
    assert await redis_helper.get_client().get(f"l4fm:list:{lease.lease_id}") is None


@pytest.mark.anyio
async def test_publish_failure_revokes_and_never_retries():
    registry = RedisLeaseRegistry()
    lease = await registry.acquire(
        7,
        10,
        f"fixture-{uuid4()}",
        "user",
        "user",
        60,
        scope="files",
        owner_session_id="tab",
    )
    publisher = AsyncMock(side_effect=RuntimeError("broker unavailable"))
    with (
        patch.object(fm.topic_publisher, "publish", publisher),
        patch.object(fm, "lease_registry", registry),
        pytest.raises(RuntimeError),
    ):
        await fm.navigate(lease, fm.Navigation(path="C:\\"))
    assert publisher.await_count == 1
    assert not (await registry.get(lease.lease_id)).is_active()


@pytest.mark.anyio
async def test_revoked_owned_close_is_idempotent_but_read_is_not():
    from api.internal_v1 import file_manager as api
    from fastapi import HTTPException, Request

    registry = LeaseRegistry()
    lease = await registry.acquire(
        7, 10, "fixture", "user", "user", 60, scope="files", owner_session_id="tab"
    )
    request = Request(
        {
            "type": "http",
            "headers": [
                (b"x-org-id", b"7"),
                (b"x-user-id", b"user"),
                (b"x-role", b"user"),
                (b"x-session-id", b"tab"),
            ],
        }
    )
    await registry.revoke(lease.lease_id)
    with (
        patch.object(api, "lease_registry", registry),
        patch.object(api, "dispatch", AsyncMock()) as dispatch,
        patch.object(
            api, "navigate", AsyncMock(return_value={"state": "completed"})
        ) as navigate,
    ):
        result = await api.signal(
            lease.lease_id, api.Signal(action="stop"), request, None
        )
        assert result["stopped"] is True
        await api.signal(lease.lease_id, api.Signal(action="stop"), request, None)
        navigate.assert_awaited_once()
        dispatch.assert_not_called()
        with pytest.raises(HTTPException) as error:
            await api.owned_lease(lease.lease_id, request)
        assert error.value.status_code == 409


@pytest.mark.anyio
@pytest.mark.parametrize("registry_type", [LeaseRegistry, RedisLeaseRegistry])
async def test_confirmed_stop_unlocks_only_revoked_files_and_not_a_new_owner(
    registry_type,
):
    registry = registry_type()
    sn = f"fixture-{uuid4()}"
    lease = await registry.acquire(
        7, 10, sn, "user", "user", 60, scope="files", owner_session_id="tab"
    )
    assert not await registry.confirm_files_stopped(lease.lease_id)
    await registry.revoke(lease.lease_id)
    assert await registry.confirm_files_stopped(lease.lease_id)
    assert await registry.touch(lease.lease_id, 60) is None
    new = await registry.acquire(
        7, 10, sn, "user", "user", 60, scope="console", owner_session_id="tab"
    )
    assert await registry.confirm_files_stopped(lease.lease_id)
    assert (await registry.get_active_by_sn(sn)).lease_id == new.lease_id


@pytest.mark.anyio
async def test_confirmed_close_waits_for_matching_terminal_result_before_unlock():
    from api.internal_v1 import file_manager as api
    from fastapi import Request

    registry = RedisLeaseRegistry()
    lease = await registry.acquire(
        7,
        10,
        f"fixture-{uuid4()}",
        "user",
        "user",
        60,
        scope="files",
        owner_session_id="tab",
    )
    request = Request(
        {
            "type": "http",
            "headers": [
                (b"x-org-id", b"7"),
                (b"x-user-id", b"user"),
                (b"x-role", b"user"),
                (b"x-session-id", b"tab"),
            ],
        }
    )

    async def navigate(old, body):
        assert body.action == "stop"
        with pytest.raises(LeaseConflictError):
            await registry.acquire(
                7,
                10,
                old.sn,
                "user",
                "user",
                60,
                scope="console",
                owner_session_id="tab",
            )
        assert await registry.touch(old.lease_id, 60) is None
        return {"state": "completed"}

    with (
        patch.object(api, "lease_registry", registry),
        patch.object(api, "navigate", navigate),
    ):
        result = await api.signal(
            lease.lease_id,
            api.Signal(action="stop"),
            request,
            None,
        )
    assert result["retry_after_sec"] == 0
    assert (
        await registry.acquire(
            7, 10, lease.sn, "user", "user", 60, scope="console", owner_session_id="tab"
        )
    ).scope == "console"


def test_v1_navigation_and_optional_close_are_rejected():
    from pydantic import ValidationError
    from api.internal_v1.file_manager import Signal

    with pytest.raises(ValidationError):
        Signal(action="list", operation_id=uuid4())
    with pytest.raises(ValidationError):
        Signal(action="stop", confirmed_close=False)
    with pytest.raises(ValidationError):
        fm.Result(
            v=1, command_id=str(uuid4()), lease_id=str(uuid4()), state="completed"
        )
