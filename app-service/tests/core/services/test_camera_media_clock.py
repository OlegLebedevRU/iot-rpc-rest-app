"""Fixed camera-attempt media expiry survives UTC jumps; Redis remains authority."""

import copy
import json
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from core.camera.media import CameraEpoch
from core.camera.media_clock import CameraMediaClock
from core.remote_input.leases import RedisLeaseRegistry
from core.remote_input.pending import PendingCommandRegistry
from core.remote_input.presence import PresenceRegistry
from core.remote_input.service import RemoteInputService
from core.remote_input.video_control import video_control

from .test_camera_media3 import configured


def test_shared_camera_clock_vectors_and_lease_dto():
    from jsonschema import Draft202012Validator, FormatChecker

    from core.remote_input.video_api import CameraLeaseView12

    packet = Path(__file__).resolve().parents[4] / "contracts/camera-media-v3-adapter"
    vectors = json.loads((packet / "clock-vectors.json").read_text())
    schema = json.loads((packet / "lease.schema.json").read_text())
    initial = vectors["initial"]
    for renewal in vectors["renewals"]:
        # This is the MEDIA monotonic renewal equation, independent of live UTC.
        deadline = initial["media_deadline_mono_ms"] + 1000 * (
            renewal["media_lease_expires_at"] - initial["media_lease_expires_at"]
        )
        assert deadline == renewal["media_deadline_mono_ms"]
        assert deadline - renewal["media_mono_ms"] == renewal["media_remaining_ms"]
        value = {
            "sn": "4623",
            "lease_id": str(uuid4()),
            "active": True,
            "scope": "stream",
            "owner_user_id": "owner",
            "owner_session_id": "session",
            "expires_at": "2027-01-01T00:00:00Z",
            "media_lease_expires_at": renewal["media_lease_expires_at"],
            "media_remaining_ms": renewal["media_remaining_ms"],
            "media_clock_id": vectors["clock_id"],
        }
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
        CameraLeaseView12.model_validate(value)
    late = vectors["delayed_start"]
    assert (
        min(
            late["current_lease_remaining_ms"],
            late["prepared_media_lease_expires_at"] * 1000 - late["coordinate_now_ms"],
        )
        == late["maximum_start_ttl_ms"]
    )


@pytest.fixture
async def clock_env():
    tick = [100000]
    wall = [time.time_ns() // 1000000]
    kernel = [str(uuid4())]
    registry = RedisLeaseRegistry()
    lease = await registry.acquire(
        org_id=1,
        device_id=4623,
        sn="clock-" + uuid4().hex,
        owner_user_id="owner",
        owner_role="user",
        owner_session_id="session",
        scope="stream",
        ttl_sec=60,
    )
    clock = CameraMediaClock(
        monotonic=lambda: tick[0], wall=lambda: wall[0], boot=lambda: kernel[0]
    )
    yield SimpleNamespace(
        clock=clock, tick=tick, wall=wall, kernel=kernel, registry=registry, lease=lease
    )
    await clock.client.delete(
        f"l4d:lease:{lease.lease_id}", f"l4d:lease:active:{lease.sn}"
    )


@pytest.mark.anyio
@pytest.mark.parametrize("jump", [-3600000, 3600000])
async def test_fixed_export_and_keepalive_delta_ignore_wall_clock(clock_env, jump):
    e = clock_env
    initial = await e.clock.export(e.lease, initialize=True)
    duplicate = await e.clock.export(e.lease, initialize=True)
    assert duplicate.media_clock_id == initial.media_clock_id
    assert duplicate.media_lease_expires_at <= initial.media_lease_expires_at
    e.tick[0] += 1000
    e.wall[0] += jump
    before = await e.clock.export(e.lease)
    assert before.media_lease_expires_at <= initial.media_lease_expires_at
    assert before.media_remaining_ms <= initial.media_remaining_ms - 1000
    await e.clock.touch(e.lease, 60)
    after = await e.clock.export(e.lease)
    assert after.media_clock_id == initial.media_clock_id
    delta = after.media_lease_expires_at - initial.media_lease_expires_at
    assert 0 <= delta <= 2  # one real heartbeat, never a one-hour wall-clock delta
    # This is the exact mapping used by MEDIA: old mono + expiry-coordinate delta.
    media_deadline = 500000 + initial.media_remaining_ms
    renewed_deadline = media_deadline + delta * 1000
    assert abs(renewed_deadline - (media_deadline + 1000)) <= 1000


@pytest.mark.anyio
async def test_late_start_consumes_original_export_and_clock_loss_never_rebases(
    clock_env,
):
    e = clock_env
    initial = await e.clock.export(e.lease, initialize=True)
    body = {
        "contract_version": 3,
        "session_id": str(uuid4()),
        "operation_id": str(uuid4()),
        "publisher": {"sn": e.lease.sn, "stream_instance_id": str(uuid4())},
        "lease_id": str(e.lease.lease_id),
        "lease_expires_at": initial.media_lease_expires_at,
        "descriptor": configured("low")["descriptor"],
    }
    e.tick[0] += 4000
    current = await e.clock.export(e.lease)
    epoch = CameraEpoch.from_start(body, e.lease, media_lease=current)
    assert epoch.start["lease_expires_at"] * 1000 - current.coordinate_now_ms < 57000
    expired = copy.deepcopy(body)
    expired["lease_expires_at"] = current.coordinate_now_ms // 1000
    with pytest.raises(ValueError, match="expired"):
        CameraEpoch.from_start(expired, e.lease, media_lease=current)
    await e.clock.client.hdel(f"l4d:lease:{e.lease.lease_id}", "camera_media_clock")
    with pytest.raises(ValueError, match="clock_lost"):
        await e.clock.export(e.lease, initialize=True)


@pytest.mark.parametrize(
    "fault",
    [
        "kernel",
        "regression",
        "corrupt",
        "expired",
        "revoked",
        "replacement",
        "missing_active",
    ],
)
@pytest.mark.anyio
async def test_lost_clock_or_lease_cannot_renew(clock_env, fault):
    e = clock_env
    await e.clock.export(e.lease, initialize=True)
    key = f"l4d:lease:{e.lease.lease_id}"
    active = f"l4d:lease:active:{e.lease.sn}"
    if fault == "kernel":
        e.kernel[0] = str(uuid4())
    elif fault == "regression":
        e.tick[0] -= 1
    elif fault == "corrupt":
        await e.clock.client.hset(key, "camera_media_clock", "{}")
    elif fault == "expired":
        e.tick[0] += 60000
    elif fault == "revoked":
        await e.clock.client.hset(key, "revoked_reason", "manual")
    elif fault == "replacement":
        await e.clock.client.set(active, str(uuid4()), ex=60)
    else:
        await e.clock.client.delete(active)
    with pytest.raises(ValueError):
        await e.clock.touch(e.lease, 60)


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner_user_id", "other"),
        ("owner_session_id", "other"),
        ("sn", "other"),
        ("scope", "input"),
    ],
)
@pytest.mark.anyio
async def test_identity_and_scope_do_not_gain_clock_bypass(clock_env, field, value):
    e = clock_env
    await e.clock.export(e.lease, initialize=True)
    with pytest.raises(ValueError):
        await e.clock.export(replace(e.lease, **{field: value}))


@pytest.mark.anyio
async def test_desktop_lease_has_no_implicit_clock_and_owner_check_stays(clock_env):
    e = clock_env
    with pytest.raises(ValueError):
        await e.clock.export(e.lease)
    service = SimpleNamespace(leases=e.registry)
    with pytest.raises(HTTPException):
        await video_control.authorize(
            service, e.lease.lease_id, 1, "other", "session", require_active=False
        )
    assert not await e.clock.client.hget(
        f"l4d:lease:{e.lease.lease_id}", "camera_media_clock_initialized"
    )


@pytest.mark.anyio
async def test_camera_keepalive_uses_trusted_anchor_and_generic_touch_is_untouched(
    clock_env, monkeypatch
):
    from core.camera import media_clock as module

    e = clock_env
    await e.clock.export(e.lease, initialize=True)
    monkeypatch.setattr(module, "camera_media_clock", e.clock)
    # A marked camera lease uses the scoped touch even when its display UTC is old.
    e.wall[0] -= 3600000
    touched = await e.clock.touch(e.lease, 60)
    assert not touched.is_active()
    service = RemoteInputService(
        leases=e.registry, presence=PresenceRegistry(), pending=PendingCommandRegistry()
    )
    monkeypatch.setattr("core.remote_input.service.send_ctl_command", AsyncMock())

    async def forbidden_generic_touch(*args):
        raise AssertionError("camera must not use generic UTC touch")

    monkeypatch.setattr(e.registry, "touch", forbidden_generic_touch)
    response = await service.keepalive(
        e.lease.lease_id, org_id=1, caller_user_id="owner", caller_session_id="session"
    )
    assert response.lease_id == e.lease.lease_id
    assert (await e.clock.export(e.lease)).media_remaining_ms > 59000


@pytest.mark.anyio
async def test_origin_sampling_regression_is_rejected_before_anchor_write(clock_env):
    e = clock_env
    samples = iter([1000, 1200, 1100])
    e.clock.monotonic = lambda: next(samples)
    with pytest.raises(ValueError, match="clock_lost"):
        await e.clock.export(e.lease, initialize=True)
    assert not await e.clock.client.hget(
        f"l4d:lease:{e.lease.lease_id}", "camera_media_clock_initialized"
    )


@pytest.mark.anyio
async def test_start_budget_is_capped_by_original_media_prepare_even_after_keepalive(
    clock_env, monkeypatch
):
    from core.camera import media_clock as module
    from core.camera.runtime import CameraRuntime

    e = clock_env
    monkeypatch.setattr(module, "camera_media_clock", e.clock)
    # The already prepared MEDIA route A has only seven seconds left.
    await e.clock.client.pexpire(f"l4d:lease:active:{e.lease.sn}", 7000)
    first = await e.clock.export(e.lease, initialize=True)
    e.tick[0] += 2000
    # A genuine heartbeat extends the server lease B, not the old START of A.
    await e.clock.touch(e.lease, 15)
    value = {
        "lease_id": str(e.lease.lease_id),
        "stream_instance_id": str(uuid4()),
        "media_clock_id": first.media_clock_id,
        "media_lease_expires_at": first.media_lease_expires_at,
    }
    budget = await CameraRuntime.check_lease(e.lease.sn, value)
    assert 0 < budget <= 5000
    wrong = {**value, "media_clock_id": str(uuid4())}
    with pytest.raises(ValueError, match="clock_mismatch"):
        await CameraRuntime.check_lease(e.lease.sn, wrong)
    e.tick[0] += 5000
    with pytest.raises(ValueError, match="lease_invalid"):
        await CameraRuntime.check_lease(e.lease.sn, value)


@pytest.mark.anyio
async def test_camera_negative_utc_display_does_not_lose_active_slot_or_cleanup(
    clock_env, monkeypatch
):
    from core.camera import media_clock as module

    e = clock_env
    await e.clock.export(e.lease, initialize=True)
    monkeypatch.setattr(module, "camera_media_clock", e.clock)
    e.wall[0] -= 86400000
    await e.clock.touch(e.lease, 60)
    assert (await e.registry.get_active(e.lease.sn)).lease_id == e.lease.lease_id
    expired = await e.registry.cleanup_expired()
    assert all(row.lease_id != e.lease.lease_id for row, _ in expired)


@pytest.mark.anyio
async def test_live_camera_cannot_fall_back_when_both_anchor_fields_are_lost(clock_env):
    e = clock_env
    await e.clock.export(e.lease, initialize=True)
    e.lease.stream_instance_id = uuid4()
    e.lease.stream_mode = "usb-camera"
    e.lease.selected_camera_id = "cam:ip000001"
    e.lease.stream_contract_version = 3
    assert await e.clock.save_stream(e.lease, None)
    await e.clock.client.hdel(
        f"l4d:lease:{e.lease.lease_id}",
        "camera_media_clock",
        "camera_media_clock_initialized",
    )
    with pytest.raises(ValueError, match="clock_lost"):
        await e.clock.export(e.lease, initialize=True)
