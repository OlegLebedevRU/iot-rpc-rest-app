"""Camera record retention follows validated renewal, never grants authority."""

import asyncio
import copy
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from core.camera.control import camera_control, epoch_of
from core.camera.runtime_wire import ADMISSION, CameraRuntimeCommand
from core.remote_input.pending import PendingCommandRegistry
from core.remote_input.presence import PresenceRegistry
from core.remote_input.service import RemoteInputService
from core.remote_input.video_control import video_control

from . import test_camera_media_clock as clock_tests

from .test_camera_media3 import configured

clock_env = clock_tests.clock_env


@pytest.fixture
async def camera_env(clock_env, monkeypatch):
    from core.camera import media_clock, runtime

    e = clock_env
    monkeypatch.setattr(media_clock, "camera_media_clock", e.clock)
    initial = await e.clock.export(e.lease, initialize=True)
    e.lease.stream_instance_id = uuid4()
    e.lease.stream_state = "running"
    e.lease.stream_mode = "usb-camera"
    assert await e.clock.save_stream(e.lease, None)
    body = {
        "contract_version": 3,
        "session_id": str(uuid4()),
        "operation_id": str(uuid4()),
        "lease_id": str(e.lease.lease_id),
        "lease_expires_at": initial.media_lease_expires_at,
        "publisher": {
            "sn": e.lease.sn,
            "stream_instance_id": str(e.lease.stream_instance_id),
        },
        "descriptor": configured("low")["descriptor"],
    }
    record = {
        "version": 2,
        "state": "running",
        "start": body,
        "admission_revision": ADMISSION,
        "media_clock_id": initial.media_clock_id,
    }
    key = video_control.store.key(e.lease.sn)
    await e.clock.client.set(key, json.dumps({"camera_stream": record}), ex=300)

    async def command(action, epoch, lease):
        assert action == "renew" and epoch.start == body
        return CameraRuntimeCommand(
            {
                "sn": lease.sn,
                "type": "lease_renew",
                "command_id": str(uuid4()),
                "lease_id": str(lease.lease_id),
                "stream_instance_id": str(lease.stream_instance_id),
                "expires_at_ms": e.tick[0] + 60000,
            }
        )

    actor = SimpleNamespace(command=AsyncMock(side_effect=command))
    monkeypatch.setattr(runtime, "camera_runtime", actor)
    sender = AsyncMock()
    monkeypatch.setattr("core.remote_input.service.send_ctl_command", sender)
    service = RemoteInputService(
        leases=e.registry, presence=PresenceRegistry(), pending=PendingCommandRegistry()
    )
    yield SimpleNamespace(
        e=e, key=key, record=record, service=service, actor=actor, sender=sender
    )
    await e.clock.client.delete(key)


async def keepalive(env):
    return await env.service.keepalive_lease(
        env.e.lease.lease_id,
        org_id=1,
        caller_user_id="owner",
        caller_session_id="session",
    )


@pytest.mark.anyio
async def test_live_camera_survives_620_seconds_without_changing_start_or_budget(
    camera_env, monkeypatch
):
    env = camera_env
    e = env.e
    redis_time = [time.time()]
    monkeypatch.setattr(time, "time", lambda: redis_time[0])
    original = copy.deepcopy(env.record)
    for _ in range(124):
        redis_time[0] += 5
        e.tick[0] += 5000
        e.wall[0] += 5000
        await keepalive(env)
        stored = await camera_control.record(e.lease.sn)
        assert stored["start"] == original["start"]
        assert stored["media_clock_id"] == original["media_clock_id"]
        assert 299 <= await e.clock.client.ttl(env.key) <= 300
        assert (
            59000
            <= await e.clock.client.pttl(f"l4d:lease:active:{e.lease.sn}")
            <= 60000
        )
    assert env.actor.command.await_count == env.sender.await_count == 124
    assert (await e.clock.export(e.lease)).media_clock_id == original["media_clock_id"]


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["missing", "stopped", "other_lease", "other_stream"])
async def test_bound_camera_missing_or_mismatched_record_fails_before_touch(
    camera_env, monkeypatch, fault
):
    env = camera_env
    record = copy.deepcopy(env.record)
    if fault == "missing":
        await env.e.clock.client.delete(env.key)
    else:
        if fault == "stopped":
            record["state"] = "stopped"
        elif fault == "other_lease":
            record["start"]["lease_id"] = str(uuid4())
        else:
            record["start"]["publisher"]["stream_instance_id"] = str(uuid4())
        await env.e.clock.client.set(
            env.key, json.dumps({"camera_stream": record}), ex=10
        )
    touch = AsyncMock(wraps=env.e.clock.touch)
    monkeypatch.setattr(env.e.clock, "touch", touch)
    with pytest.raises(HTTPException) as exc:
        await keepalive(env)
    assert exc.value.status_code == 409
    touch.assert_not_awaited()
    env.actor.command.assert_not_awaited()
    env.sender.assert_not_awaited()


@pytest.mark.anyio
async def test_replacement_during_touch_cannot_fall_back_to_legacy_publish(
    camera_env, monkeypatch
):
    env = camera_env
    original_touch = env.e.clock.touch
    replacement = copy.deepcopy(env.record)
    replacement["start"]["publisher"]["stream_instance_id"] = str(uuid4())

    async def touch(*args):
        value = await original_touch(*args)
        await env.e.clock.client.set(
            env.key, json.dumps({"camera_stream": replacement}), ex=7
        )
        return value

    monkeypatch.setattr(env.e.clock, "touch", touch)
    with pytest.raises(HTTPException) as exc:
        await keepalive(env)
    assert exc.value.status_code == 409
    env.actor.command.assert_not_awaited()
    env.sender.assert_not_awaited()
    assert await env.e.clock.client.ttl(env.key) <= 7


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["stop", "replace", "clock", "revoke"])
async def test_retention_guard_cannot_touch_concurrent_stop_replacement_or_revocation(
    camera_env, monkeypatch, fault
):
    env = camera_env
    e = env.e
    expected = epoch_of(env.record)
    replacement = copy.deepcopy(env.record)
    if fault == "stop":
        replacement["state"] = "stopped"
    elif fault == "replace":
        replacement["start"]["descriptor"]["descriptor_revision"] = str(uuid4())
    elif fault == "clock":
        replacement["media_clock_id"] = str(uuid4())
    await e.clock.client.set(env.key, json.dumps({"camera_stream": replacement}), ex=7)
    if fault == "revoke":
        await e.clock.client.delete(f"l4d:lease:active:{e.lease.sn}")
    result = await camera_control.update(
        expected,
        expected_states=("starting", "running"),
        authority_service=env.service,
        last_renew_command_id=str(uuid4()),
    )
    assert result is None
    assert await e.clock.client.ttl(env.key) <= 7
    assert await camera_control.record(e.lease.sn) == replacement


@pytest.mark.anyio
async def test_deleted_record_is_never_recreated_by_delayed_renew(camera_env):
    env = camera_env
    await env.e.clock.client.delete(env.key)
    result = await camera_control.update(
        epoch_of(env.record),
        expected_states=("starting", "running"),
        authority_service=env.service,
        last_renew_command_id=str(uuid4()),
    )
    assert result is None and not await env.e.clock.client.exists(env.key)


@pytest.mark.anyio
async def test_watch_retry_preserves_a_concurrent_replacement(camera_env, monkeypatch):
    env = camera_env
    original_guard = camera_control.publisher_lease
    calls = 0
    replacement = copy.deepcopy(env.record)
    replacement["start"]["publisher"]["stream_instance_id"] = str(uuid4())

    async def guard(*args):
        nonlocal calls
        lease = await original_guard(*args)
        calls += 1
        if calls == 1:
            await env.e.clock.client.set(
                env.key, json.dumps({"camera_stream": replacement}), ex=7
            )
        return lease

    monkeypatch.setattr(camera_control, "publisher_lease", guard)
    result = await camera_control.update(
        epoch_of(env.record),
        expected_states=("starting", "running"),
        authority_service=env.service,
        last_renew_command_id=str(uuid4()),
    )
    assert calls >= 2 and result is None
    assert await camera_control.record(env.e.lease.sn) == replacement
    assert await env.e.clock.client.ttl(env.key) <= 7


@pytest.mark.anyio
async def test_metadata_refresh_does_not_extend_authority_deadline_or_ttl(camera_env):
    env = camera_env
    active_key = f"l4d:lease:active:{env.e.lease.sn}"
    await env.e.clock.client.pexpire(env.key, 2000)
    active_before = await env.e.clock.client.pttl(active_key)
    clock_before = await env.e.clock.export(env.e.lease)
    result = await camera_control.update(
        epoch_of(env.record),
        expected_states=("starting", "running"),
        authority_service=env.service,
        last_renew_command_id=str(uuid4()),
    )
    assert result is not None
    assert 299 <= await env.e.clock.client.ttl(env.key) <= 300
    assert await env.e.clock.client.pttl(active_key) <= active_before
    clock_after = await env.e.clock.export(env.e.lease)
    assert clock_after.media_clock_id == clock_before.media_clock_id
    assert clock_after.media_lease_expires_at == clock_before.media_lease_expires_at


@pytest.mark.anyio
async def test_refreshed_metadata_survives_its_original_short_expiry(camera_env):
    env = camera_env
    await env.e.clock.client.pexpire(env.key, 1500)
    await keepalive(env)
    await asyncio.sleep(1.6)
    assert await camera_control.record(env.e.lease.sn)
    assert await env.e.clock.client.ttl(env.key) >= 297
    assert await env.e.clock.client.pttl(f"l4d:lease:active:{env.e.lease.sn}") < 59000
