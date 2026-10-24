from __future__ import annotations

import asyncio
import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from core.config import settings
from core.remote_input import video_models as wire
from core.remote_input.leases import (
    LeaseRegistry,
    _dict_to_lease,
    _lease_to_dict,
)
from core.remote_input.mqtt_bridge import decode_ctl_payload, handle_device_ctl_message
from core.remote_input.presence import PresenceRegistry
from core.remote_input.schemas import CtlPresence, DisplayInfo, InventoryInfo
from core.remote_input.service import RemoteInputService
from core.remote_input.video_api import VideoStateView
from core.remote_input.video_control import (
    now_ms,
    select_codec,
    video_control,
)
from fastapi import HTTPException
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[4]
PACKAGE = ROOT / "contracts/hevc-v2"


def fixture(name):
    return json.loads((PACKAGE / "fixtures" / f"{name}.json").read_text())["payload"]


@pytest.mark.parametrize("invalid", [None, False, 1, "local_utc"])
def test_monotonic_admission_marker_is_explicit_and_strict(invalid):
    cap = fixture("capabilities")["video_capabilities"]
    with pytest.raises(ValidationError):
        wire.Capabilities.model_validate(dict(cap, admission_clock=invalid))


@pytest.mark.anyio
@pytest.mark.parametrize(
    "reason", ["lease_invalid", "caller_cancelled", "start_timeout", "conflict"]
)
async def test_control_failure_preserves_hardware_applicability(env, reason):
    _, lease, start, cap = env
    await video_control.store.change(
        lease.sn,
        lambda doc: doc.update(
            stream={"version": 2, "start": start, "state": "starting"}
        ),
    )
    assert await video_control.finish(
        lease.sn, start["stream_instance_id"], "failed", reason
    )
    document = await video_control.store.get(lease.sn)
    assert document["capability"] == cap
    assert document["stream"]["error"]["current_stream_terminated"] is False


@pytest.mark.anyio
async def test_start_refresh_reconfirms_cached_measurement_despite_read_cooldown(env):
    service, lease, _, cap = env
    cap["source_id"] = "disp:fixture"
    measured = now_ms() - 86400000
    cap["measured_at_ms"] = measured
    await video_control.store.change(
        lease.sn,
        lambda doc: doc.update(
            capability=cap,
            probe_source_id="disp:fixture",
            probe_profile_id="low",
            next_probe_ms=now_ms() + 30000,
        ),
    )
    observed = []

    async def send(sn, query, **kwargs):
        observed.append(query.command_id)
        ack = fixture("capabilities")
        ack["command_id"] = query.command_id
        cap.update(checked_at_ms=now_ms(), valid_until_ms=now_ms() + 59000)
        ack["video_capabilities"] = cap
        assert await video_control.accept_capability(
            sn, wire.CapabilitiesAck.model_validate(ack)
        )

    result = await video_control.capability(
        lease.sn,
        service.presence,
        send,
        refresh=True,
        source_id="disp:fixture",
        profile_id="low",
    )
    assert (
        result["negotiated_v2"]
        and result["video_capabilities"]["measured_at_ms"] == measured
    )
    assert len(observed) == 1


@pytest.mark.parametrize("invalid", [None, 0, -1, "123", 5000000000001])
def test_memory_capability_rejects_invalid_measurement(invalid):
    cap = fixture("capabilities")["video_capabilities"]
    with pytest.raises(ValidationError):
        wire.Capabilities.model_validate(dict(cap, measured_at_ms=invalid))


@pytest.mark.anyio
@pytest.mark.parametrize("invalidation", ["transport", "presence"])
async def test_invalidated_admission_reconfirms_without_old_probe_cooldown(
    env, invalidation
):
    service, lease, _, cap = env
    cap["source_id"] = "disp:fixture"
    cap["admission_clock"] = "issuer_monotonic_v1"
    cap["measured_at_ms"] = now_ms() - 86400000
    await video_control.store.change(
        lease.sn,
        lambda doc: doc.update(
            capability=cap,
            probe_source_id="disp:fixture",
            probe_profile_id="low",
            next_probe_ms=now_ms() + 30000,
        ),
    )
    if invalidation == "transport":
        await video_control.invalidate(lease.sn)
    else:
        await video_control.observe_presence(
            lease.sn,
            CtlPresence(
                timestamp=datetime.now(UTC).isoformat(),
                capabilities=["video_contract_v2"],
                session_id=2,
                desktop_available=True,
            ),
        )
    assert not (await video_control.store.get(lease.sn)).get("capability")
    observed = []

    async def send(sn, query, **kwargs):
        observed.append(query.command_id)
        ack = fixture("capabilities")
        ack["command_id"] = query.command_id
        cap.update(checked_at_ms=now_ms(), valid_until_ms=now_ms() + 59000)
        ack["video_capabilities"] = cap
        assert await video_control.accept_capability(
            sn, wire.CapabilitiesAck.model_validate(ack)
        )

    result = await video_control.capability(
        lease.sn, service.presence, send, source_id="disp:fixture", profile_id="low"
    )
    assert result["negotiated_v2"] and len(observed) == 1
    assert result["video_capabilities"]["measured_at_ms"] == cap["measured_at_ms"]


def test_memory_capability_rejects_measurement_after_check():
    cap = fixture("capabilities")["video_capabilities"]
    with pytest.raises(ValidationError):
        wire.Capabilities.model_validate(
            dict(cap, measured_at_ms=cap["checked_at_ms"] + 1)
        )


@pytest.mark.anyio
async def test_memory_old_measurement_fresh_correlated_response(env):
    service, lease, _, cap = env
    await video_control.invalidate(lease.sn)
    measured = now_ms() - 86400000

    async def send(sn, query, **kwargs):
        ack = fixture("capabilities")
        ack["command_id"] = query.command_id
        cap.update(
            measured_at_ms=measured,
            checked_at_ms=now_ms(),
            valid_until_ms=now_ms() + 59000,
        )
        ack["video_capabilities"] = cap
        assert not await video_control.accept_capability(
            sn, wire.CapabilitiesAck.model_validate(dict(ack, command_id=str(uuid4())))
        )
        assert await video_control.accept_capability(
            sn, wire.CapabilitiesAck.model_validate(ack)
        )

    result = await video_control.capability(lease.sn, service.presence, send)
    assert result["negotiated_v2"]
    assert result["video_capabilities"]["measured_at_ms"] == measured


@pytest.mark.anyio
async def test_memory_missing_profile_bypasses_other_profile_cache_cooldown(env):
    service, lease, _, cap = env
    cap["source_id"] = "disp:fixture"
    cap["video"][0]["profiles"] = [
        p for p in cap["video"][0]["profiles"] if p["profile_id"] == "low"
    ]
    await video_control.store.change(
        lease.sn,
        lambda doc: doc.update(
            capability=cap,
            probe_source_id=cap["source_id"],
            probe_profile_id="low",
            next_probe_ms=now_ms() + 30000,
        ),
    )

    async def send(sn, query, **kwargs):
        assert query.profile_id == "default"
        ack = fixture("capabilities")
        ack["command_id"] = query.command_id
        ack["video_capabilities"].update(
            source_id=query.source_id,
            checked_at_ms=now_ms(),
            valid_until_ms=now_ms() + 59000,
        )
        assert await video_control.accept_capability(
            sn, wire.CapabilitiesAck.model_validate(ack)
        )

    assert (
        await video_control.capability(
            lease.sn,
            service.presence,
            send,
            source_id="disp:fixture",
            profile_id="default",
        )
    )["negotiated_v2"]


@pytest.mark.parametrize("invalid", [None, "", "hd", 123])
def test_memory_inventory_profile_strict(invalid):
    inventory = fixture("inventory_get")
    with pytest.raises(ValidationError):
        wire.InventoryGet.model_validate(dict(inventory, profile_id=invalid))


@pytest.mark.parametrize(
    "path",
    [
        p
        for p in sorted((PACKAGE / "fixtures").glob("*.json"))
        if json.loads(p.read_text())["definition"]
        in {
            "start",
            "ready",
            "error",
            "inventory_get",
            "capabilities_ack",
            "stop",
            "lease_renew",
            "start_ack",
            "nack",
        }
    ],
    ids=lambda p: p.stem,
)
def test_actual_v2_models(path):
    case = json.loads(path.read_text())
    model = {
        "start": wire.Start,
        "ready": wire.Ready,
        "error": wire.Error,
        "inventory_get": wire.InventoryGet,
        "capabilities_ack": wire.CapabilitiesAck,
        "stop": wire.Stop,
        "lease_renew": wire.LeaseRenew,
        "start_ack": wire.StartAck,
        "nack": wire.Nack,
    }.get(case["definition"])
    assert model is not None
    if case["valid"]:
        assert (
            model.model_validate(case["payload"]).model_dump(mode="json")
            == case["payload"]
        )
    else:
        with pytest.raises(ValidationError):
            model.model_validate(case["payload"])


def test_runtime_schema_matches_frozen_package():
    assert (ROOT / "app-service/core/remote_input/video.schema.json").read_bytes() == (
        PACKAGE / "hevc.schema.json"
    ).read_bytes()


@pytest.mark.parametrize("source", ["disp:secondary", "disp:primary"])
def test_source_inventory_extension_retains_legacy_wire(source):
    old = fixture("inventory_get")
    assert wire.InventoryGet.model_validate(old).model_dump(mode="json") == old
    targeted = dict(old, source_id=source)
    assert (
        wire.InventoryGet.model_validate(targeted).model_dump(mode="json") == targeted
    )
    for invalid in ["", "x" * 64, None, 123]:
        with pytest.raises(ValidationError):
            wire.InventoryGet.model_validate(dict(old, source_id=invalid))


@pytest.mark.anyio
async def test_selected_source_reprobes_other_cached_source_and_correlates_ack(env):
    service, lease, _, cap = env
    cap["source_id"] = "disp:primary"
    await video_control.store.change(
        lease.sn, lambda doc: doc.update(capability=cap, next_probe_ms=now_ms() + 30000)
    )
    observed = []

    async def send(sn, query, **kwargs):
        observed.append(query.model_dump(mode="json"))
        assert query.source_id == "disp:secondary"
        ack = fixture("capabilities")
        ack["command_id"] = query.command_id
        ack["video_capabilities"].update(
            source_id="disp:primary",
            checked_at_ms=now_ms(),
            valid_until_ms=now_ms() + 59000,
        )
        assert not await video_control.accept_capability(
            sn, wire.CapabilitiesAck.model_validate(ack)
        )
        ack["video_capabilities"]["source_id"] = "disp:secondary"
        assert await video_control.accept_capability(
            sn, wire.CapabilitiesAck.model_validate(ack)
        )

    result = await video_control.capability(
        lease.sn, service.presence, send, source_id="disp:secondary"
    )
    assert result["negotiated_v2"]
    assert result["video_capabilities"]["source_id"] == "disp:secondary"
    assert len(observed) == 1
    sender = AsyncMock(
        side_effect=AssertionError("fresh selected source must be cached")
    )
    assert (
        await video_control.capability(
            lease.sn, service.presence, sender, source_id="disp:secondary"
        )
    )["negotiated_v2"]
    sender.assert_not_called()


@pytest.mark.anyio
async def test_selected_source_does_not_replace_live_pending_probe(env):
    service, lease, _, _ = env
    await video_control.store.change(
        lease.sn,
        lambda doc: doc.update(
            pending={
                "command_id": "owned",
                "source_id": "disp:primary",
                "expires_at_ms": now_ms() + 5000,
            }
        ),
    )
    sender = AsyncMock()
    result = await video_control.capability(
        lease.sn, service.presence, sender, source_id="disp:secondary"
    )
    sender.assert_not_called()
    assert not result["negotiated_v2"]
    assert (await video_control.store.get(lease.sn))["pending"]["command_id"] == "owned"


@pytest.mark.parametrize(
    "case",
    json.loads((PACKAGE / "scenarios.json").read_text()),
    ids=lambda c: c["name"],
)
def test_prepare_vectors_use_production_decision(case):
    assert select_codec(case["start"], case["context"]) == case["expected"]


def test_camera_backend_requires_server_test_context():
    cases = json.loads((PACKAGE / "scenarios.json").read_text())
    case = copy.deepcopy(next(item for item in cases if item["expected"] == "h265"))
    start, context = case["start"], case["context"]
    start["codec_policy"] = "h265"
    start["descriptor"].update(source_type="usb-camera", source_id="test-rtsp-camera")
    context["capabilities"]["source_id"] = "test-rtsp-camera"
    context["capabilities"]["video"][0].update(backend="camera", hardware=False)
    assert select_codec(start, context) == "unsupported"
    context["test_camera_source"] = True
    assert select_codec(start, context) == "h265"
    start["descriptor"]["source_type"] = "desktop"
    assert select_codec(start, context) == "unsupported"


def test_wire_rejects_duplicates_oversize_and_unknown_nested():
    with pytest.raises(ValueError):
        decode_ctl_payload('{"v":2,"v":1}')
    with pytest.raises(ValueError):
        decode_ctl_payload(b" " * 32769 + b'{"v":2}')
    ready = fixture("hevc_ready")
    ready["actual_descriptor"]["tracks"][0]["unknown"] = 1
    with pytest.raises(ValidationError):
        decode_ctl_payload(ready)


@pytest.fixture
async def env(monkeypatch):
    monkeypatch.setattr(settings.remote_input, "video_v2_enabled", True)
    monkeypatch.setattr(settings.remote_input, "video_hevc_chain_ready", True)
    leases, presence = LeaseRegistry(), PresenceRegistry()
    service = RemoteInputService(leases=leases, presence=presence)
    lease = await leases.acquire(
        org_id=1,
        device_id=10,
        sn="hevc-fixture",
        owner_user_id="owner",
        owner_session_id="session",
        owner_role="admin",
        ttl_sec=60,
        scope="input",
    )
    await video_control.store.client.delete(
        *(
            await video_control.store.client.keys(
                video_control.store.key(lease.sn) + "*"
            )
        )
        or ["unused-test-key"]
    )
    await presence.update(
        lease.sn,
        CtlPresence(
            timestamp=datetime.now(UTC).isoformat(),
            capabilities=["video_contract_v2"],
            session_id=1,
            desktop_available=True,
        ),
    )
    await presence.update_inventory(
        lease.sn,
        InventoryInfo(
            displays=[
                DisplayInfo(
                    desktop_id="display-0",
                    name="display",
                    width=1280,
                    height=720,
                    session_id=1,
                )
            ]
        ),
    )
    start = fixture("hevc_start")
    start.update(
        lease_id=str(lease.lease_id),
        issued_at_ms=now_ms(),
        expires_at_ms=now_ms() + 2000,
        lease_expires_at_ms=int(lease.expires_at.timestamp() * 1000),
    )
    cap = fixture("capabilities")["video_capabilities"]
    cap.update(checked_at_ms=now_ms(), valid_until_ms=now_ms() + 59000)
    server_epoch = await video_control.store.current_epoch()
    await video_control.store.change(
        lease.sn, lambda doc: doc.update(capability=cap, server_epoch=server_epoch)
    )
    yield service, lease, start, cap
    await video_control.store.client.delete(
        *(
            await video_control.store.client.keys(
                video_control.store.key(lease.sn) + "*"
            )
        )
        or ["unused-test-key"]
    )


@pytest.mark.anyio
@pytest.mark.parametrize("refresh", [False, True])
async def test_chain_gate_closes_inventory_admission(env, monkeypatch, refresh):
    service, lease, _start, _cap = env
    before = await video_control.store.get(lease.sn)
    monkeypatch.setattr(settings.remote_input, "video_hevc_chain_ready", False)
    sender = AsyncMock(side_effect=AssertionError("disabled admission must not probe"))

    result = await video_control.capability(
        lease.sn, service.presence, sender, refresh=refresh
    )

    assert result == {"negotiated_v2": False, "video_capabilities": None}
    sender.assert_not_called()
    assert await video_control.store.get(lease.sn) == before


@pytest.mark.anyio
async def test_chain_gate_inventory_preserves_running_epoch(env, monkeypatch):
    service, lease, start, _cap = env

    async def send(sn, command, **kwargs):
        if command.type == "stream_start":
            assert await ready_for(service, start)

    sender = AsyncMock(side_effect=send)
    await video_control.start(
        service, wire.Start.model_validate(start), 1, "owner", "session", sender
    )
    before = await video_control.store.get(lease.sn)
    stream_id = lease.stream_instance_id
    monkeypatch.setattr(settings.remote_input, "video_hevc_chain_ready", False)

    result = await video_control.capability(lease.sn, service.presence, sender)

    assert result == {"negotiated_v2": False, "video_capabilities": None}
    assert await video_control.store.get(lease.sn) == before
    assert lease.stream_instance_id == stream_id
    assert before["stream"]["state"] == "running"
    assert sender.await_count == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "camera,allowlisted,negotiated",
    [(True, True, True), (True, False, False), (False, True, False)],
)
async def test_chain_gate_preserves_only_explicit_test_camera_exception(
    env, monkeypatch, camera, allowlisted, negotiated
):
    service, lease, _start, cap = env
    monkeypatch.setattr(settings.remote_input, "video_hevc_chain_ready", False)
    monkeypatch.setattr(
        settings.remote_input,
        "video_test_camera_sns",
        [lease.sn] if allowlisted else [],
    )
    if camera:
        cap["source_id"] = "test-fixture-camera"
        cap["video"][0].update(backend="camera", hardware=False)
    await video_control.store.change(lease.sn, lambda doc: doc.update(capability=cap))
    before = await video_control.store.get(lease.sn)
    sender = AsyncMock()

    result = await video_control.capability(lease.sn, service.presence, sender)

    assert result == {
        "negotiated_v2": negotiated,
        "video_capabilities": cap if negotiated else None,
    }
    sender.assert_not_called()
    assert await video_control.store.get(lease.sn) == before


async def ready_for(service, start):
    event = fixture("hevc_ready")
    event["sn"] = start["sn"]
    for key in (
        "lease_id",
        "stream_instance_id",
        "command_id",
        "operation_id",
        "agent_instance_id",
    ):
        event[key] = start[key]
    event["actual_descriptor"] = copy.deepcopy(start["descriptor"])
    return await handle_device_ctl_message(
        routing_key=f"dev.{start['sn']}.ctl",
        payload=event,
        p_registry=service.presence,
        l_registry=service.leases,
    )


@pytest.mark.anyio
async def test_start_ready_duplicate_failure_and_all_subscribers(env):
    service, lease, start, _cap = env
    queues = [await service.presence.subscribe_stream(lease.sn) for _ in range(3)]

    async def send(sn, command, **kwargs):
        assert command.v == 2
        if command.type == "stream_start":
            assert await ready_for(service, start)

    sender = AsyncMock(side_effect=send)
    command = wire.Start.model_validate(start)
    state = await video_control.start(service, command, 1, "owner", "session", sender)
    assert state["state"] == "running"
    assert (await video_control.start(service, command, 1, "owner", "session", sender))[
        "result"
    ] == "already_running"
    assert sender.await_count == 1
    event = fixture("runtime_error")
    event["lease_id"] = str(lease.lease_id)
    assert await handle_device_ctl_message(
        routing_key=f"dev.{lease.sn}.ctl",
        payload=event,
        p_registry=service.presence,
        l_registry=service.leases,
    )
    doc = await video_control.store.get(lease.sn)
    view = VideoStateView.from_record(doc["stream"])
    assert view.model_dump(mode="json")["error"] == event["error"]
    assert doc["capability"]["video"][0]["status"] == "temporarily_unavailable"
    assert lease.stream_instance_id is None
    assert sender.await_count == 1  # no recovery or codec fallback
    for queue in queues:
        assert (await queue.get()).state == "running"
        assert (await queue.get()).state == "failed"
    assert not await video_control.event(
        lease.sn, wire.Error.model_validate(event), service, sender
    )


@pytest.mark.anyio
async def test_concurrent_duplicate_sends_only_one_start(env):
    service, _lease, start, _ = env

    async def send(*args, **kwargs):
        await asyncio.sleep(0.02)
        await ready_for(service, start)

    sender = AsyncMock(side_effect=send)
    results = await asyncio.gather(
        *[
            video_control.start(
                service, wire.Start.model_validate(start), 1, "owner", "session", sender
            )
            for _ in range(3)
        ]
    )
    assert sender.await_count == 1
    assert sorted(r["result"] for r in results) == [
        "already_running",
        "already_running",
        "started",
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "alter,expected",
    [
        ("tenant", "forbidden"),
        ("owner", "forbidden"),
        ("session", "forbidden"),
        ("source", "forbidden"),
        ("deadline", "lease_mismatch"),
        ("expired", "expired"),
        ("stale", "stale_capability"),
        ("unsupported", "unsupported"),
        ("chain", "unsupported"),
        ("epoch", "capability_mismatch"),
        ("geometry", "capability_mismatch"),
    ],
)
async def test_admission_rejects_before_dispatch(env, monkeypatch, alter, expected):
    service, lease, start, cap = env
    start["codec_policy"] = "h265"
    org, user, session = 1, "owner", "session"
    if alter == "tenant":
        org = 2
    if alter == "owner":
        user = "other"
    if alter == "session":
        session = "other"
    if alter == "source":
        start["descriptor"]["source_id"] = "denied"
    if alter == "deadline":
        start["lease_expires_at_ms"] += 1000
    if alter == "expired":
        start.update(issued_at_ms=now_ms() - 2000, expires_at_ms=now_ms() - 1)
    if alter == "stale":
        cap.update(checked_at_ms=now_ms() - 60000, valid_until_ms=now_ms() - 1)
    if alter == "unsupported":
        cap["video"][0].update(
            status="unsupported", profiles=[], reason_code="no_hardware_mft"
        )
    if alter == "chain":
        monkeypatch.setattr(settings.remote_input, "video_hevc_chain_ready", False)
    if alter == "epoch":
        start["agent_instance_id"] = str(uuid4())
    if alter == "geometry":
        start["descriptor"]["geometry_generation"] += 1
    await video_control.store.change(lease.sn, lambda doc: doc.update(capability=cap))
    sender = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await video_control.start(
            service, wire.Start.model_validate(start), org, user, session, sender
        )
    assert exc.value.detail["code"] == expected
    sender.assert_not_called()


@pytest.mark.anyio
async def test_capability_correlated_nonce_and_old_cached_ready(env):
    service, lease, _, cap = env
    ack = fixture("capabilities")
    ack["video_capabilities"] = cap
    assert not await video_control.accept_capability(
        lease.sn, wire.CapabilitiesAck.model_validate(ack)
    )
    await video_control.invalidate(lease.sn)

    async def send(sn, query, **kwargs):
        ack["command_id"] = query.command_id
        ack["video_capabilities"].update(
            checked_at_ms=now_ms(), valid_until_ms=now_ms() + 59000
        )
        assert await video_control.accept_capability(
            sn, wire.CapabilitiesAck.model_validate(ack)
        )

    result = await video_control.capability(lease.sn, service.presence, send)
    assert result["negotiated_v2"]
    assert not await video_control.accept_capability(
        lease.sn, wire.CapabilitiesAck.model_validate(ack)
    )
    await video_control.store.change(
        lease.sn, lambda doc: doc.update(server_epoch="previous-server")
    )
    assert not (
        await video_control.capability(lease.sn, service.presence, AsyncMock())
    )["negotiated_v2"]


@pytest.mark.anyio
async def test_ready_mismatch_terminal_and_stale_error_isolation(env):
    service, lease, start, _ = env
    sender = AsyncMock()
    task = asyncio.create_task(
        video_control.start(
            service, wire.Start.model_validate(start), 1, "owner", "session", sender
        )
    )
    while not sender.await_count:
        await asyncio.sleep(0)
    event = fixture("hevc_ready")
    event["lease_id"] = str(lease.lease_id)
    event["actual_descriptor"]["tracks"][0]["width"] = 640
    assert await video_control.event(
        lease.sn, wire.Ready.model_validate(event), service, sender
    )
    result = await task
    assert result["state"] == "failed" and result["reason"] == "descriptor_mismatch"
    assert [call.args[1].type for call in sender.await_args_list] == [
        "stream_start",
        "stream_stop",
    ]


@pytest.mark.anyio
async def test_redis_workers_receive_same_terminal_event_without_legacy_storage(env):
    from core.remote_input.presence import RedisPresenceRegistry
    from core.remote_input.schemas import CtlStreamEvent

    _, lease, _, _ = env
    workers = [RedisPresenceRegistry(), RedisPresenceRegistry()]
    queues = [await worker.subscribe_stream(lease.sn) for worker in workers]
    event = CtlStreamEvent(
        sn=lease.sn,
        stream_instance_id=uuid4(),
        state="failed",
        reason="producer_lost",
        timestamp=datetime.now(UTC).isoformat(),
    )
    try:
        await workers[0].notify_video_event(event)
        received = await asyncio.gather(
            *[asyncio.wait_for(q.get(), 1.0) for q in queues]
        )
        assert received[0].model_dump() == received[1].model_dump()
        assert not await video_control.store.client.exists(f"l4d:stream:{lease.sn}")
    finally:
        for worker in workers:
            worker._video_relay.cancel()
        await asyncio.gather(*[w._video_relay for w in workers], return_exceptions=True)


@pytest.mark.anyio
async def test_stop_old_epoch_and_watcher_leave_preserve_publisher(env):
    service, lease, start, _ = env

    async def send(sn, command, **kwargs):
        if command.type == "stream_start":
            await ready_for(service, start)

    sender = AsyncMock(side_effect=send)
    await video_control.start(
        service, wire.Start.model_validate(start), 1, "owner", "session", sender
    )
    queue = await service.presence.subscribe_stream(lease.sn)
    await service.presence.unsubscribe_stream(lease.sn, queue)
    assert (await video_control.store.get(lease.sn))["stream"]["state"] == "running"
    old = fixture("stop")
    old.update(
        lease_id=str(lease.lease_id),
        issued_at_ms=now_ms(),
        expires_at_ms=now_ms() + 1000,
        stream_instance_id=str(uuid4()),
    )
    with pytest.raises(HTTPException):
        await video_control.stop(
            service, wire.Stop.model_validate(old), 1, "owner", "session", sender
        )
    error = fixture("runtime_error")
    error.update(lease_id=str(lease.lease_id), stream_instance_id=str(uuid4()))
    assert not await video_control.event(
        lease.sn, wire.Error.model_validate(error), service, sender
    )
    assert (await video_control.store.get(lease.sn))["stream"]["state"] == "running"
    old["stream_instance_id"] = start["stream_instance_id"]
    command = wire.Stop.model_validate(old)
    first = await video_control.stop(service, command, 1, "owner", "session", sender)
    second = await video_control.stop(service, command, 1, "owner", "session", sender)
    assert first["state"] == second["state"] == "stopped"
    assert first["reason"] == second["reason"] == "user_requested"
    assert [c.args[1].type for c in sender.await_args_list] == [
        "stream_start",
        "stream_stop",
    ]


@pytest.mark.anyio
async def test_timeout_stops_once_keeps_error_and_never_falls_back(env, monkeypatch):
    service, lease, start, _ = env
    admitted_at = now_ms()
    # Expire deterministically after START publication. Setup wall time must not
    # select the separate pre-admission expired rejection on loaded CI.
    clock = [admitted_at]
    monkeypatch.setattr("core.remote_input.video_control.now_ms", lambda: clock[0])
    start["expires_at_ms"] = admitted_at + 80

    async def expire_after_dispatch(sn, command, **kwargs):
        if command.type == "stream_start":
            clock[0] = admitted_at + 81

    sender = AsyncMock(side_effect=expire_after_dispatch)
    with pytest.raises(HTTPException) as exc:
        await video_control.start(
            service, wire.Start.model_validate(start), 1, "owner", "session", sender
        )
    assert exc.value.status_code == 502
    doc = await video_control.store.get(lease.sn)
    assert doc["stream"]["state"] == "failed"
    assert doc["stream"]["error"]["code"] == "producer_lost"
    assert lease.stream_instance_id is None
    assert [c.args[1].type for c in sender.await_args_list] == [
        "stream_start",
        "stream_stop",
    ]


@pytest.mark.anyio
async def test_live_profile_change_conflicts_before_dispatch(env):
    service, _, start, _ = env

    async def send(*args, **kwargs):
        await ready_for(service, start)

    sender = AsyncMock(side_effect=send)
    await video_control.start(
        service, wire.Start.model_validate(start), 1, "owner", "session", sender
    )
    changed = copy.deepcopy(start)
    changed["descriptor"]["profile_id"] = "default"
    with pytest.raises(HTTPException) as exc:
        await video_control.start(
            service, wire.Start.model_validate(changed), 1, "owner", "session", sender
        )
    assert exc.value.detail["code"] == "conflict"
    assert sender.await_count == 1


@pytest.mark.anyio
async def test_explicit_opt_in_h264_uses_v2_and_legacy_agent_gets_no_v2(env):
    service, lease, start, _cap = env
    h264 = fixture("h264_v2_start")
    for key in ("lease_id", "issued_at_ms", "expires_at_ms", "lease_expires_at_ms"):
        h264[key] = start[key]

    async def send(*args, **kwargs):
        assert await ready_for(service, h264)

    sender = AsyncMock(side_effect=send)
    state = await video_control.start(
        service, wire.Start.model_validate(h264), 1, "owner", "session", sender
    )
    assert state["state"] == "running" and state["start"]["resolved_codec"] == "h264"
    await service.presence.update(
        lease.sn, CtlPresence(timestamp=datetime.now(UTC).isoformat(), version="999.0")
    )
    sender.reset_mock()
    result = await video_control.capability(
        lease.sn, service.presence, sender, refresh=True
    )
    assert result == {"negotiated_v2": False, "video_capabilities": None}
    sender.assert_not_called()


def test_additive_lease_serialization(env=None):
    # Legacy hashes preserve their defaults; v2 fields survive a Redis round trip.
    from core.remote_input.leases import Lease

    lease = Lease(uuid4(), 1, 10, "fixture", "owner", "admin")
    raw = _lease_to_dict(lease)
    raw.pop("stream_contract_version")
    raw.pop("stream_profile")
    assert _dict_to_lease(raw).stream_contract_version == 1
    lease.stream_contract_version, lease.stream_profile = 2, "low"
    assert _dict_to_lease(_lease_to_dict(lease)).stream_profile == "low"


@pytest.mark.anyio
@pytest.mark.parametrize("loss", ["missing", "expired", "revoked"])
async def test_orphan_running_epoch_allows_fresh_manual_start(env, loss):
    from core.remote_input.leases import RedisLeaseRegistry

    service, lease, start, cap = env
    client = video_control.store.client
    service.leases = RedisLeaseRegistry()
    await client.hset(f"l4d:lease:{lease.lease_id}", mapping=_lease_to_dict(lease))
    await client.set(f"l4d:lease:active:{lease.sn}", str(lease.lease_id))

    async def send(sn, command, **kwargs):
        if command.type == "stream_start":
            await ready_for(service, command.model_dump(mode="json"))

    sender = AsyncMock(side_effect=send)
    await video_control.start(
        service, wire.Start.model_validate(start), 1, "owner", "session", sender
    )
    assert (await video_control.store.get(lease.sn))["stream"]["state"] == "running"
    # Simulate Redis TTL/revocation after the worker that owned A disappeared.
    if loss == "missing":
        await client.delete(f"l4d:lease:{lease.lease_id}")
    else:
        await client.hset(
            f"l4d:lease:{lease.lease_id}",
            mapping=(
                {"expires_at": "2020-01-01T00:00:00+00:00"}
                if loss == "expired"
                else {"revoked_reason": "owner_logout"}
            ),
        )
    await client.delete(f"l4d:lease:active:{lease.sn}")
    await handle_device_ctl_message(
        routing_key=f"dev.{lease.sn}.ctl",
        payload={
            "v": 1,
            "type": "presence",
            "timestamp": datetime.now(UTC).isoformat(),
            "status": "online",
            "session_id": 1,
            "desktop_available": True,
            "capabilities": ["video_contract_v2"],
            "stream": {
                "state": "stopped",
                "stream_instance_id": start["stream_instance_id"],
            },
        },
        p_registry=service.presence,
        l_registry=service.leases,
    )
    await video_control.invalidate(lease.sn)
    service.leases = RedisLeaseRegistry()
    new_lease = await service.leases.acquire(
        org_id=1,
        device_id=10,
        sn=lease.sn,
        owner_user_id="owner",
        owner_session_id="session",
        owner_role="admin",
        scope="input",
        ttl_sec=60,
    )
    new_start = copy.deepcopy(start)
    new_start.update(
        lease_id=str(new_lease.lease_id),
        stream_instance_id=str(uuid4()),
        operation_id=str(uuid4()),
        command_id=str(uuid4()),
        agent_instance_id=str(uuid4()),
        issued_at_ms=now_ms(),
        expires_at_ms=now_ms() + 2000,
        lease_expires_at_ms=int(new_lease.expires_at.timestamp() * 1000),
    )
    cap["agent_instance_id"] = new_start["agent_instance_id"]
    await video_control.store.change(lease.sn, lambda doc: doc.update(capability=cap))
    queue = await service.presence.subscribe_stream(lease.sn)
    result = await video_control.start(
        service, wire.Start.model_validate(new_start), 1, "owner", "session", sender
    )
    assert result["state"] == "running"
    terminal = await asyncio.wait_for(queue.get(), 1)
    assert str(terminal.stream_instance_id) == start["stream_instance_id"]
    assert terminal.state == "stopped"
    assert [c.args[1].type for c in sender.await_args_list] == [
        "stream_start",
        "stream_stop",
        "stream_start",
    ]
    assert (
        sender.await_args_list[1].args[1].agent_instance_id
        == start["agent_instance_id"]
    )
    error = fixture("runtime_error")
    error["lease_id"] = str(lease.lease_id)
    assert not await video_control.event(
        lease.sn, wire.Error.model_validate(error), service, sender
    )
    assert (await video_control.store.get(lease.sn))["stream"] == result


@pytest.mark.anyio
@pytest.mark.parametrize("loss", ["missing", "expired", "revoked"])
async def test_exact_runtime_error_after_lease_loss_is_terminal(env, loss):
    service, lease, start, _ = env

    async def send(*args, **kwargs):
        await ready_for(service, start)

    await video_control.start(
        service,
        wire.Start.model_validate(start),
        1,
        "owner",
        "session",
        AsyncMock(side_effect=send),
    )
    if loss == "missing":
        service.leases._leases_by_id.pop(lease.lease_id)
    elif loss == "expired":
        lease.expires_at = datetime(2020, 1, 1, tzinfo=UTC)
    else:
        lease.revoked_reason = "owner_logout"
    error = fixture("runtime_error")
    error["lease_id"] = str(lease.lease_id)
    queue = await service.presence.subscribe_stream(lease.sn)
    assert await video_control.event(
        lease.sn, wire.Error.model_validate(error), service, AsyncMock()
    )
    state = (await video_control.store.get(lease.sn))["stream"]
    assert state["state"] == "failed" and state["error"] == error["error"]
    assert (await asyncio.wait_for(queue.get(), 1)).state == "failed"


async def redis_running(env):
    from core.remote_input.leases import RedisLeaseRegistry

    service, lease, start, _ = env
    service.leases = RedisLeaseRegistry()
    client = video_control.store.client
    await client.hset(f"l4d:lease:{lease.lease_id}", mapping=_lease_to_dict(lease))
    await client.set(f"l4d:lease:active:{lease.sn}", str(lease.lease_id))

    async def send(sn, command, **kwargs):
        if command.type == "stream_start":
            await ready_for(service, start)

    await video_control.start(
        service,
        wire.Start.model_validate(start),
        1,
        "owner",
        "session",
        AsyncMock(side_effect=send),
    )
    return service, lease, start, client


@pytest.mark.anyio
async def test_cleanup_discovers_missing_lease_without_active_key_and_is_idempotent(
    env,
):
    service, lease, start, client = await redis_running(env)
    await client.delete(f"l4d:lease:{lease.lease_id}", f"l4d:lease:active:{lease.sn}")
    await video_control.store.reset_server_epoch()
    await video_control.invalidate(lease.sn)
    sender = AsyncMock()
    queue = await service.presence.subscribe_stream(lease.sn)
    await asyncio.gather(
        video_control.cleanup(service, sender), video_control.cleanup(service, sender)
    )
    state = (await video_control.store.get(lease.sn))["stream"]
    assert state["state"] == "stopped" and state["reason"] == "lease_invalid"
    assert (
        str((await asyncio.wait_for(queue.get(), 1)).stream_instance_id)
        == start["stream_instance_id"]
    )
    assert queue.empty()
    sender.assert_awaited_once()
    # Reconciliation/probing cannot keep a LIVE orphan alive by extending TTL.
    await client.expire(video_control.store.key(lease.sn), 20)
    await video_control.cleanup(service, sender)
    assert await client.ttl(video_control.store.key(lease.sn)) <= 20
    assert not await client.exists(f"l4d:lease:{lease.lease_id}")


@pytest.mark.anyio
async def test_cleanup_preserves_live_publisher_and_renewal_race(env, monkeypatch):
    service, lease, start, client = await redis_running(env)
    sender = AsyncMock()
    assert not await video_control.reconcile(lease.sn, service, sender)
    # Even a concurrent repair/renewal of the lease invalidates retirement's WATCH.
    await client.hset(
        f"l4d:lease:{lease.lease_id}", "expires_at", "2020-01-01T00:00:00+00:00"
    )
    original = video_control.publisher_lease
    raced = False

    async def renew(service, candidate, pipe):
        nonlocal raced
        result = await original(service, candidate, pipe)
        if not raced:
            raced = True
            await client.hset(
                f"l4d:lease:{lease.lease_id}",
                "expires_at",
                lease.expires_at.isoformat(),
            )
        return result

    monkeypatch.setattr(video_control, "publisher_lease", renew)
    assert not await video_control.reconcile(lease.sn, service, sender)
    assert raced
    assert (await video_control.store.get(lease.sn))["stream"]["state"] == "running"
    changed = copy.deepcopy(start)
    changed.update(stream_instance_id=str(uuid4()), operation_id=str(uuid4()))
    with pytest.raises(HTTPException) as exc:
        await video_control.start(
            service, wire.Start.model_validate(changed), 1, "owner", "session", sender
        )
    assert exc.value.detail == {"code": "conflict"}
    sender.assert_not_called()


@pytest.mark.anyio
async def test_start_revocation_between_guard_and_commit_sends_no_start(
    env, monkeypatch
):
    from core.remote_input.leases import RedisLeaseRegistry

    service, lease, start, _ = env
    client = video_control.store.client
    service.leases = RedisLeaseRegistry()
    await client.hset(f"l4d:lease:{lease.lease_id}", mapping=_lease_to_dict(lease))
    await client.set(f"l4d:lease:active:{lease.sn}", str(lease.lease_id))
    original = video_control.publisher_lease
    raced = False

    async def revoke(service, candidate, pipe):
        nonlocal raced
        result = await original(service, candidate, pipe)
        if not raced:
            raced = True
            await client.hset(
                f"l4d:lease:{lease.lease_id}", "revoked_reason", "owner_logout"
            )
        return result

    monkeypatch.setattr(video_control, "publisher_lease", revoke)
    sender = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await video_control.start(
            service, wire.Start.model_validate(start), 1, "owner", "session", sender
        )
    assert exc.value.detail == {"code": "lease_invalid"}
    assert raced and "stream" not in await video_control.store.get(lease.sn)
    sender.assert_not_called()


@pytest.mark.anyio
async def test_v2_cached_read_does_not_restore_missing_or_revoked_lease(env):
    service, lease, _, client = await redis_running(env)
    await service.leases.get(lease.lease_id)
    await client.hset(f"l4d:lease:{lease.lease_id}", "revoked_reason", "owner_logout")
    assert (await service.leases.get(lease.lease_id)).revoked_reason == "owner_logout"
    await client.delete(f"l4d:lease:{lease.lease_id}")
    assert await service.leases.get(lease.lease_id) is None
    assert not await client.exists(f"l4d:lease:{lease.lease_id}")


@pytest.mark.anyio
async def test_ready_after_expiry_cannot_revive_starting_publisher(env):
    from core.remote_input.leases import RedisLeaseRegistry

    service, lease, start, _ = env
    service.leases = RedisLeaseRegistry()
    client = video_control.store.client
    await client.hset(f"l4d:lease:{lease.lease_id}", mapping=_lease_to_dict(lease))
    await client.set(f"l4d:lease:active:{lease.sn}", str(lease.lease_id))
    sender = AsyncMock()
    task = asyncio.create_task(
        video_control.start(
            service, wire.Start.model_validate(start), 1, "owner", "session", sender
        )
    )
    try:
        for _ in range(100):
            if sender.await_count:
                break
            await asyncio.sleep(0.001)
        assert sender.await_count
        await client.hset(
            f"l4d:lease:{lease.lease_id}", "expires_at", "2020-01-01T00:00:00+00:00"
        )
        assert not await ready_for(service, start)
        assert await video_control.reconcile(lease.sn, service, sender)
        assert (await asyncio.wait_for(task, 1))["state"] == "stopped"
        assert not await ready_for(service, start)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.anyio
async def test_old_agent_error_preserves_new_agent_probe(env):
    service, lease, start, cap = env

    async def send(*args, **kwargs):
        await ready_for(service, start)

    await video_control.start(
        service,
        wire.Start.model_validate(start),
        1,
        "owner",
        "session",
        AsyncMock(side_effect=send),
    )
    cap["agent_instance_id"] = str(uuid4())
    await video_control.store.change(lease.sn, lambda doc: doc.update(capability=cap))
    error = fixture("runtime_error")
    error["lease_id"] = str(lease.lease_id)
    malformed = copy.deepcopy(error)
    malformed["descriptor_revision"] = str(uuid4())
    assert not await video_control.event(
        lease.sn, wire.Error.model_validate(malformed), service, AsyncMock()
    )
    assert await video_control.event(
        lease.sn, wire.Error.model_validate(error), service, AsyncMock()
    )
    assert (await video_control.store.get(lease.sn))["capability"] == cap


@pytest.mark.anyio
async def test_real_http_v2_response_error_and_legacy_validation(env, monkeypatch):
    from api.internal_v1 import remote_input as api
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    service, lease, start, _ = env
    monkeypatch.setattr(api, "remote_input_service", service)
    monkeypatch.setattr(settings.auth, "internal_service_key", "test-secret")

    async def send(*args, **kwargs):
        await ready_for(service, start)

    monkeypatch.setattr(api, "send_ctl_command", send)
    app = FastAPI()
    app.include_router(api.router)
    base = f"{api.router.prefix}/lease/{lease.lease_id}"
    headers = {
        "X-Internal-Service-Key": "test-secret",
        "X-Org-Id": "1",
        "X-User-Id": "owner",
        "X-Session-Id": "session",
        "X-Role": "user",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=headers
    ) as client:
        context = await client.get(base + "/video-lease")
        assert context.status_code == 200, context.text
        assert context.json()["owner_session_id"] == "session"
        assert context.json()["active"] is True
        for caller in (
            {"X-Org-Id": "2"},
            {"X-User-Id": "other"},
            {"X-Session-Id": "other"},
            {"X-Role": "superuser", "X-Session-Id": "other"},
        ):
            assert (
                await client.get(base + "/video-lease", headers=caller)
            ).status_code == 403
        invalid = copy.deepcopy(start)
        invalid["descriptor"]["unknown"] = True
        assert (
            await client.post(base + "/stream/start", json=invalid)
        ).status_code == 400
        assert (
            await client.post(
                base + "/stream/start", json={"mode": "desktop", "unknown": True}
            )
        ).status_code == 422
        raw = json.dumps(start).replace('"v": 2', '"v": 2, "v": 2')
        assert (
            await client.post(
                base + "/stream/start",
                content=raw,
                headers={"Content-Type": "application/json"},
            )
        ).status_code == 400
        # Router imports/negative cases must not consume this command's live TTL.
        start.update(issued_at_ms=now_ms(), expires_at_ms=now_ms() + 2000)
        response = await client.post(base + "/stream/start", json=start)
        assert response.status_code == 200, response.text
        assert response.json()["resolved_codec"] == "h265"
        assert response.json()["descriptor"] == start["descriptor"]
        assert response.json()["agent_instance_id"] == start["agent_instance_id"]
        assert response.json()["lease_id"] == str(lease.lease_id)
        assert response.json()["confirmation"] == "agent_ready"
        event = fixture("runtime_error")
        event["lease_id"] = str(lease.lease_id)
        assert await video_control.event(
            lease.sn, wire.Error.model_validate(event), service, AsyncMock()
        )
        state = await client.get(base + "/video-state")
        assert state.status_code == 200
        assert state.json()["error"] == event["error"]
        denied = await client.get(base + "/video-state", headers={"X-Org-Id": "2"})
        assert denied.status_code == 403
        # A later legacy publisher can reuse this lease. Its current state must
        # not be replaced by a retained failed HEVC record from the prior epoch.
        lease.stream_contract_version = 1
        lease.stream_instance_id = uuid4()
        assert (await client.get(base + "/video-state")).status_code == 404
        assert (await video_control.store.get(lease.sn))["stream"]["error"] == event[
            "error"
        ]


@pytest.mark.anyio
async def test_restarted_worker_invalidates_capability_for_all_workers(env):
    from core.remote_input.video_control import VideoControl

    service, _, start, _ = env
    await VideoControl().store.reset_server_epoch()
    sender = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await video_control.start(
            service, wire.Start.model_validate(start), 1, "owner", "session", sender
        )
    assert exc.value.detail["code"] == "unsupported"
    sender.assert_not_called()


@pytest.mark.anyio
async def test_capability_timeout_and_prequery_cache_do_not_negotiate(env, monkeypatch):
    import core.remote_input.video_control as control_module

    service, lease, _, cap = env
    await video_control.invalidate(lease.sn)
    clock = now_ms()
    monkeypatch.setattr(control_module, "now_ms", lambda: clock)

    async def send(sn, query, **kwargs):
        nonlocal clock
        ack = fixture("capabilities")
        ack["command_id"] = query.command_id
        cap.update(checked_at_ms=clock - 1000, valid_until_ms=clock + 59000)
        ack["video_capabilities"] = cap
        assert not await video_control.accept_capability(
            sn, wire.CapabilitiesAck.model_validate(ack)
        )
        clock = query.expires_at_ms + 1

    result = await video_control.capability(lease.sn, service.presence, send)
    assert result == {"negotiated_v2": False, "video_capabilities": None}
    assert "pending" not in await video_control.store.get(lease.sn)


@pytest.mark.anyio
async def test_capability_negotiation_accepts_real_priority_probe_after_five_seconds(
    env, monkeypatch
):
    import core.remote_input.video_control as control_module

    service, lease, _, cap = env
    await video_control.invalidate(lease.sn)
    clock = now_ms()
    monkeypatch.setattr(control_module, "now_ms", lambda: clock)

    async def send(sn, query, **kwargs):
        nonlocal clock
        assert query.expires_at_ms - query.issued_at_ms == 10000
        assert kwargs["ttl_ms"] == 10000
        clock += 6200
        ack = fixture("capabilities")
        ack["command_id"] = query.command_id
        cap.update(checked_at_ms=clock, valid_until_ms=clock + 60000)
        ack["video_capabilities"] = cap
        assert await video_control.accept_capability(
            sn, wire.CapabilitiesAck.model_validate(ack)
        )

    result = await video_control.capability(lease.sn, service.presence, send)
    assert result["negotiated_v2"] is True
    assert result["video_capabilities"] == cap


@pytest.mark.anyio
@pytest.mark.parametrize(
    "case",
    [
        c
        for c in json.loads((PACKAGE / "lifecycle.json").read_text())
        if c["action"] != "media_start"
    ],
    ids=lambda c: c["name"],
)
async def test_g0_lifecycle_vectors_against_handlers(env, case):
    service, lease, start, _ = env

    async def send(*args, **kwargs):
        if case["action"] != "ready":
            await ready_for(service, start)

    sender = AsyncMock(side_effect=send)
    task = asyncio.create_task(
        video_control.start(
            service, wire.Start.model_validate(start), 1, "owner", "session", sender
        )
    )
    for _ in range(100):
        if sender.await_count:
            break
        await asyncio.sleep(0.001)
    assert sender.await_count
    if case["action"] == "ready":
        ready = copy.deepcopy(case["ready"])
        ready["lease_id"] = str(lease.lease_id)
        assert await video_control.event(
            lease.sn, wire.Ready.model_validate(ready), service, sender
        )
        result = await asyncio.wait_for(task, 1)
        assert (
            "agent_ready_only" if result["state"] == "running" else result["reason"]
        ) == case["expected"]
        return
    await asyncio.wait_for(task, 1)
    if case["action"] == "watcher_leave":
        queue = await service.presence.subscribe_stream(lease.sn)
        await service.presence.unsubscribe_stream(lease.sn, queue)
        outcome = "detach_only"
    elif case["action"] == "event":
        event = copy.deepcopy(case["event"])
        event["lease_id"] = str(lease.lease_id)
        if case.get("stale_stream"):
            event["stream_instance_id"] = "00000000-0000-4000-8000-000000000099"
        accepted = await video_control.event(
            lease.sn, wire.Error.model_validate(event), service, sender
        )
        outcome = "terminate_and_invalidate_capability" if accepted else "ignore"
    else:
        stop = fixture("stop")
        stop.update(
            lease_id=str(lease.lease_id),
            issued_at_ms=now_ms(),
            expires_at_ms=now_ms() + 1000,
        )
        if case.get("stale_stream"):
            stop["stream_instance_id"] = "00000000-0000-4000-8000-000000000099"
        try:
            await video_control.stop(
                service, wire.Stop.model_validate(stop), 1, "owner", "session", sender
            )
            outcome = "stop_owned_publisher"
        except HTTPException as exc:
            assert exc.detail["code"] == "conflict"
            outcome = "ignore"
    assert outcome == case["expected"]


def test_new_agent_v1_bootstrap_is_readable_by_old_server():
    from core.remote_input.schemas import CtlInboundAdapter, StreamStartCommand
    from jsonschema import Draft202012Validator

    legacy = json.loads((PACKAGE / "legacy/presence.json").read_text())["payload"]
    legacy["capabilities"] = [*(legacy.get("capabilities") or []), "video_contract_v2"]
    snapshot = json.loads((PACKAGE / "legacy/CtlPresence.schema.json").read_text())
    Draft202012Validator(snapshot).validate(legacy)
    assert CtlInboundAdapter.validate_python(legacy).v == 1
    # With no v2 query from the old server, both command and reply stay v1.
    start = json.loads((PACKAGE / "legacy/h264_start.wire.json").read_text())
    assert StreamStartCommand.model_validate(start).v == 1


@pytest.mark.anyio
async def test_redis_v2_lease_persists_profile_and_revocation_sends_only_v2_stop(
    env, monkeypatch
):
    from core.remote_input import leases as lease_module
    from core.remote_input.leases import RedisLeaseRegistry

    service, _, start, _ = env
    service.leases = RedisLeaseRegistry()
    # Use a distinct serial so existing legacy regression records cannot interfere.
    sn = "hevc-redis-fixture"
    lease = await service.leases.acquire(
        org_id=1,
        device_id=10,
        sn=sn,
        owner_user_id="owner",
        owner_session_id="session",
        owner_role="admin",
        scope="input",
        ttl_sec=60,
    )
    document = await video_control.store.get(start["sn"])
    await video_control.store.client.set(
        video_control.store.key(sn), json.dumps(document), ex=300
    )
    await service.presence.update(
        sn,
        CtlPresence(
            timestamp=datetime.now(UTC).isoformat(),
            capabilities=["video_contract_v2"],
            session_id=1,
            desktop_available=True,
        ),
    )
    await service.presence.update_inventory(
        sn, await service.presence.get_inventory(start["sn"])
    )
    start.update(
        sn=sn,
        lease_id=str(lease.lease_id),
        lease_expires_at_ms=int(lease.expires_at.timestamp() * 1000),
    )

    async def send(sn, command, **kwargs):
        if command.type == "stream_start":
            await ready_for(service, start)

    sender = AsyncMock(side_effect=send)
    monkeypatch.setattr(lease_module, "send_ctl_command", sender)
    try:
        await video_control.start(
            service, wire.Start.model_validate(start), 1, "owner", "session", sender
        )
        loaded = await RedisLeaseRegistry().get(lease.lease_id)
        assert loaded.stream_contract_version == 2 and loaded.stream_profile == "low"
        assert str(loaded.stream_instance_id) == start["stream_instance_id"]
        await service.leases.revoke(lease.lease_id, "owner_logout")
        record = (await video_control.store.get(sn))["stream"]
        assert record["state"] == "stopped" and record["reason"] == "owner_logout"
        assert [c.args[1].v for c in sender.await_args_list] == [2, 2]
        assert [c.args[1].type for c in sender.await_args_list] == [
            "stream_start",
            "stream_stop",
        ]
    finally:
        keys = await video_control.store.client.keys(video_control.store.key(sn) + "*")
        await video_control.store.client.delete(
            *keys, f"l4d:lease:{lease.lease_id}", f"l4d:lease:active:{sn}"
        )


# Unified media v3 uses the existing CTL2 transport and lease lifecycle.
@pytest.fixture
async def native_env(env):
    service, lease, start, cap = env
    start["descriptor"]["contract_version"] = 3
    track = start["descriptor"]["tracks"][0]
    track.update(width=3000, height=2000, fps=15, level_id=150)
    cap["contract_version"] = 3
    for entry in cap["video"]:
        if entry["codec"] == "h265":
            entry["profiles"] = [
                {"profile_id": profile, "track": copy.deepcopy(track)}
                for profile in ("low", "default")
            ]
    await video_control.store.change(
        lease.sn, lambda doc: doc.update(capability=cap, media_selection=3)
    )
    return service, lease, start, cap


@pytest.mark.parametrize("profile", ["low", "default"])
@pytest.mark.parametrize("size", [(800, 600), (1920, 1080), (3000, 2000), (1080, 1920)])
def test_media3_concrete_track_schema(profile, size):
    start = fixture("hevc_start")
    start["descriptor"].update(contract_version=3, profile_id=profile)
    start["descriptor"]["tracks"][0].update(
        width=size[0], height=size[1], fps=30, level_id=150
    )
    assert wire.Start.model_validate(start).model_dump(mode="json") == start
    del start["descriptor"]["contract_version"]
    if size[0] > 1920 or size[1] > 1080 or start["descriptor"]["tracks"][0]["fps"] > 25:
        with pytest.raises(ValidationError):
            wire.Start.model_validate(start)


@pytest.mark.anyio
@pytest.mark.parametrize("profile", ["low", "default"])
async def test_media3_inventory_start_ready_state_and_bound_renew(
    native_env, monkeypatch, profile
):
    from api.internal_v1 import remote_input as api
    from core.remote_input import service as service_module
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    service, lease, start, cap = native_env
    start["descriptor"]["profile_id"] = profile
    monkeypatch.setattr(api, "remote_input_service", service)
    monkeypatch.setattr(api, "presence_registry", service.presence)
    monkeypatch.setattr(settings.auth, "internal_service_key", "test-secret")
    sent = []

    async def send(sn, command, **kwargs):
        sent.append(command.model_dump(mode="json"))
        if command.type == "inventory_get":
            cap.update(checked_at_ms=now_ms(), valid_until_ms=now_ms() + 59000)
            ack = fixture("capabilities")
            ack.update(command_id=command.command_id, video_capabilities=cap)
            assert await video_control.accept_capability(
                sn, wire.CapabilitiesAck.model_validate(ack)
            )
        elif command.type == "stream_start":
            assert await ready_for(service, start)

    monkeypatch.setattr(api, "send_ctl_command", send)
    monkeypatch.setattr(service_module, "send_ctl_command", send)
    # The HTTP inventory path performs the normal tenant lookup.
    monkeypatch.setattr(api.DeviceRepo, "get_device_id", AsyncMock(return_value=10))
    app = FastAPI()
    app.include_router(api.router)

    async def session_override():
        yield None

    app.dependency_overrides[api.db_helper.session_getter] = session_override
    headers = {
        "X-Internal-Service-Key": "test-secret",
        "X-Org-Id": "1",
        "X-User-Id": "owner",
        "X-Session-Id": "session",
        "X-Role": "user",
        "X-L4-Media-Contract": "l4-media/3.0.0",
    }
    base = f"{api.router.prefix}/lease/{lease.lease_id}"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=headers
    ) as client:
        inventory = await client.get(
            f"{api.router.prefix}/devices/{lease.sn}/video-capabilities",
            params={
                "refresh": True,
                "source_id": cap["source_id"],
                "profile_id": profile,
            },
        )
        assert inventory.status_code == 200, inventory.text
        assert inventory.json()["video_capabilities"] == cap
        assert inventory.json()["contract_version"] == 3
        assert sent[0]["v"] == 2 and sent[0]["profile_id"] == profile
        start.update(issued_at_ms=now_ms(), expires_at_ms=now_ms() + 2000)
        response = await client.post(base + "/stream/start", json=start)
        assert response.status_code == 200, response.text
        assert response.json()["contract_version"] == 3
        assert response.json()["descriptor"] == start["descriptor"]
        assert response.json()["actual_descriptor"] == start["descriptor"]
        state = await client.get(base + "/video-state")
        assert state.status_code == 200 and state.json() == response.json()
        assert (
            await client.get(
                base + "/video-state", headers={"X-L4-Media-Contract": "l4-media/2.0.0"}
            )
        ).status_code == 422
        await service.keepalive_lease(
            lease.lease_id,
            org_id=1,
            caller_user_id="owner",
            caller_session_id="session",
        )
        assert sent[-1]["type"] == "lease_renew" and sent[-1]["v"] == 2
        assert sent[-1]["stream_instance_id"] == start["stream_instance_id"]
        assert (
            sent[-1]["descriptor_revision"]
            == start["descriptor"]["descriptor_revision"]
        )
        assert sent[-1]["lease_expires_at_ms"] <= int(
            lease.expires_at.timestamp() * 1000
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "mismatch", ["source", "geometry", "version", "track", "resource"]
)
async def test_media3_admission_keeps_exact_native_facts(native_env, mismatch):
    service, _, start, cap = native_env
    if mismatch == "source":
        cap["source_id"] = "other"
    elif mismatch == "geometry":
        cap["binding"]["geometry_generation"] += 1
    elif mismatch == "version":
        del cap["contract_version"]
        for entry in cap["video"]:
            for profile in entry["profiles"]:
                profile["track"].update(width=1280, height=720, level_id=93)
    elif mismatch == "track":
        start["descriptor"]["tracks"][0]["fps"] = 30
    else:
        start["descriptor"]["tracks"][0].update(width=4000, height=3000)
    await video_control.store.change(
        start["sn"], lambda doc: doc.update(capability=cap)
    )
    send = AsyncMock()
    with pytest.raises(HTTPException):
        await video_control.start(
            service, wire.Start.model_validate(start), 1, "owner", "session", send
        )
    send.assert_not_awaited()


@pytest.mark.anyio
async def test_media3_old_cache_is_reconfirmed_and_busy_retains_probe_memory(
    native_env,
):
    service, lease, _, cap = native_env
    old = copy.deepcopy(cap)
    del old["contract_version"]
    for entry in old["video"]:
        for profile in entry["profiles"]:
            profile["track"].update(width=1280, height=720, level_id=93)
    await video_control.store.change(
        lease.sn, lambda doc: doc.update(capability=old, media_selection=2)
    )
    observed = []

    async def send(sn, command, **kwargs):
        observed.append(command)
        cap.update(checked_at_ms=now_ms(), valid_until_ms=now_ms() + 59000)
        ack = fixture("capabilities")
        ack.update(command_id=command.command_id, video_capabilities=cap)
        assert await video_control.accept_capability(
            sn, wire.CapabilitiesAck.model_validate(ack)
        )

    result = await video_control.capability(
        lease.sn, service.presence, send, contract_version=3
    )
    assert result["video_capabilities"]["contract_version"] == 3
    assert len(observed) == 1
    memory = copy.deepcopy((await video_control.store.get(lease.sn))["probe_memory"])
    # Opening UI again reuses fresh applicability, without a new probe.
    await video_control.capability(lease.sn, service.presence, send, contract_version=3)
    assert len(observed) == 1
    for entry in cap["video"]:
        entry.update(
            status="temporarily_unavailable", reason_code="encoder_busy", profiles=[]
        )
    await video_control.capability(
        lease.sn, service.presence, send, refresh=True, contract_version=3
    )
    doc = await video_control.store.get(lease.sn)
    assert doc["probe_memory"] == memory
    assert doc["capability"]["video"][0]["reason_code"] == "encoder_busy"


@pytest.mark.anyio
async def test_media3_rejects_mixed_correlated_inventory(native_env):
    service, lease, _, cap = native_env

    async def send(sn, command, **kwargs):
        ack = fixture("capabilities")
        cap.update(checked_at_ms=now_ms(), valid_until_ms=now_ms() + 59000)
        ack.update(command_id=command.command_id, video_capabilities=cap)
        assert not await video_control.accept_capability(
            sn, wire.CapabilitiesAck.model_validate(ack)
        )
        await video_control.store.change(sn, lambda doc: doc.pop("pending", None))

    result = await video_control.capability(
        lease.sn, service.presence, send, refresh=True, contract_version=2
    )
    assert result["video_capabilities"] is None


@pytest.mark.parametrize("version", [None, 0, 2, 4, "3", True])
def test_media3_invalid_version_never_uses_native_dimensions(version):
    value = fixture("hevc_start")
    value["descriptor"]["tracks"][0].update(width=3000, height=2000, level_id=150)
    value["descriptor"]["contract_version"] = version
    with pytest.raises(ValidationError):
        wire.Start.model_validate(value)


@pytest.mark.parametrize(
    "selected,actual", [(None, 3), ("l4-media/3.0.0", 2), ("l4-media/unknown", 3)]
)
def test_media3_http_requires_exact_selection(selected, actual):
    from core.remote_input.video_api import require_media_version
    from starlette.requests import Request

    headers = [] if selected is None else [(b"x-l4-media-contract", selected.encode())]
    request = Request({"type": "http", "headers": headers})
    descriptor = {} if actual == 2 else {"contract_version": actual}
    with pytest.raises(HTTPException) as exc:
        require_media_version(request, descriptor)
    assert exc.value.status_code == 422


@pytest.mark.anyio
async def test_media3_busy_does_not_authorize_saved_success(native_env):
    service, lease, start, cap = native_env
    memory = copy.deepcopy(cap)
    for entry in cap["video"]:
        entry.update(
            status="temporarily_unavailable", reason_code="encoder_busy", profiles=[]
        )
    await video_control.store.change(
        lease.sn, lambda doc: doc.update(capability=cap, probe_memory=memory)
    )
    sender = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await video_control.start(
            service, wire.Start.model_validate(start), 1, "owner", "session", sender
        )
    assert exc.value.detail == {"code": "unsupported"}
    sender.assert_not_awaited()
    assert (await video_control.store.get(lease.sn))["probe_memory"] == memory


def test_media3_coordinator_schema_is_pinned():
    import hashlib

    package = ROOT / "contracts/l4-media-v3"
    manifest = json.loads((package / "manifest.json").read_text())
    assert (
        hashlib.sha256((package / "media.schema.json").read_bytes()).hexdigest()
        == manifest["schema_sha256"]
    )


@pytest.mark.parametrize("descriptor", [None, [], "invalid"])
def test_media3_malformed_nested_descriptor_is_validation_error(descriptor):
    value = fixture("hevc_start")
    value["descriptor"] = descriptor
    with pytest.raises(ValidationError):
        wire.Start.model_validate(value)


@pytest.mark.anyio
async def test_media3_auto_accepts_only_declared_h264_candidate(native_env):
    service, lease, start, cap = native_env
    track = fixture("h264_v2_start")["descriptor"]["tracks"][0]
    track.update(
        width=3000, height=2000, fps=15, codec_profile="high", profile_level_id="640033"
    )
    start.update(codec_policy="auto", resolved_codec="h264")
    start["descriptor"]["tracks"] = [track]
    entry = cap["video"][0]
    entry.update(
        codec="h264",
        backend="openh264",
        hardware=False,
        profiles=[
            {
                "profile_id": start["descriptor"]["profile_id"],
                "track": copy.deepcopy(track),
            }
        ],
    )
    cap["video"] = [entry]
    await video_control.store.change(lease.sn, lambda doc: doc.update(capability=cap))

    async def send(sn, command, **kwargs):
        assert command.resolved_codec.value == "h264"
        assert await ready_for(service, start)

    state = await video_control.start(
        service, wire.Start.model_validate(start), 1, "owner", "session", send
    )
    assert state["actual_descriptor"] == start["descriptor"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "version,source,budget",
    [
        (3, None, 35000),
        (3, "display-0", 35000),
        (3, "camera-source", 10000),
        (2, "display-0", 10000),
    ],
)
async def test_cold_desktop_inventory_window_and_immediate_memory_hit(
    env, monkeypatch, version, source, budget
):
    import core.remote_input.video_control as control_module
    from core.remote_input.publisher import send_ctl_command
    from core.remote_input import publisher

    service, lease, _, cap = env
    if version == 3:
        cap["contract_version"] = 3
    if source:
        cap["source_id"] = source
    measured = now_ms() - 86400000
    cap["measured_at_ms"] = measured
    await video_control.invalidate(lease.sn)
    clock = now_ms()
    monkeypatch.setattr(control_module, "now_ms", lambda: clock)
    broker = AsyncMock()
    monkeypatch.setattr(publisher.topic_publisher, "publish", broker)
    calls = []

    async def send(sn, query, **kwargs):
        nonlocal clock
        calls.append(query.command_id)
        assert query.v == 2
        assert query.expires_at_ms - query.issued_at_ms == budget
        assert kwargs["ttl_ms"] == budget
        await send_ctl_command(sn, query, **kwargs)
        assert broker.call_args.kwargs["expiration"] == budget
        assert broker.call_args.kwargs["correlation_id"] == query.command_id
        clock += 31000 if budget == 35000 else 9500
        if budget == 35000:
            waiting = await video_control.capability(
                lease.sn,
                service.presence,
                send,
                source_id=source,
                contract_version=version,
            )
            assert not waiting["negotiated_v2"] and len(calls) == 1
        cap.update(checked_at_ms=clock, valid_until_ms=clock + 59000)
        ack = fixture("capabilities")
        ack.update(command_id=query.command_id, video_capabilities=cap)
        assert not await video_control.accept_capability(
            sn, wire.CapabilitiesAck.model_validate(dict(ack, command_id=str(uuid4())))
        )
        assert await video_control.accept_capability(
            sn, wire.CapabilitiesAck.model_validate(ack)
        )

    result = await video_control.capability(
        lease.sn, service.presence, send, source_id=source, contract_version=version
    )
    assert result["negotiated_v2"]
    assert result["video_capabilities"]["measured_at_ms"] == measured
    assert len(calls) == 1
    again = await video_control.capability(
        lease.sn, service.presence, send, source_id=source, contract_version=version
    )
    assert again == result and len(calls) == 1


@pytest.mark.anyio
async def test_cold_desktop_inventory_ack_at_deadline_is_rejected(
    native_env, monkeypatch
):
    import core.remote_input.video_control as control_module

    service, lease, _, cap = native_env
    clock = now_ms()
    monkeypatch.setattr(control_module, "now_ms", lambda: clock)

    async def send(sn, query, **kwargs):
        nonlocal clock
        assert query.expires_at_ms - query.issued_at_ms == 35000
        clock = query.expires_at_ms
        cap.update(checked_at_ms=clock, valid_until_ms=clock + 59000)
        ack = fixture("capabilities")
        ack.update(command_id=query.command_id, video_capabilities=cap)
        assert not await video_control.accept_capability(
            sn, wire.CapabilitiesAck.model_validate(ack)
        )

    result = await video_control.capability(
        lease.sn, service.presence, send, refresh=True, contract_version=3
    )
    assert result["video_capabilities"] is None
    assert "pending" not in await video_control.store.get(lease.sn)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "budget,offset,expected",
    [
        (35000, 34999, True),
        (35000, 35000, False),
        (20000, 19999, True),
        (20000, 20000, False),
    ],
)
async def test_cold_desktop_ready_respects_command_window_and_publish_ttl(
    native_env, monkeypatch, budget, offset, expected
):
    import core.remote_input.video_control as control_module

    service, lease, start, _ = native_env
    clock = now_ms()
    monkeypatch.setattr(control_module, "now_ms", lambda: clock)
    if budget == 20000:
        lease.expires_at = datetime.fromtimestamp((clock + budget) / 1000, UTC)
        start["lease_expires_at_ms"] = clock + budget
    start.update(
        issued_at_ms=clock,
        expires_at_ms=min(clock + 35000, start["lease_expires_at_ms"]),
    )
    before_deadline = lease.expires_at
    sent = []

    async def send(sn, command, **kwargs):
        nonlocal clock
        sent.append(command.type)
        if command.type == "stream_start":
            assert kwargs["ttl_ms"] == budget
            assert command.expires_at_ms <= command.lease_expires_at_ms
            clock += offset
            event = fixture("hevc_ready")
            for key in (
                "sn",
                "lease_id",
                "stream_instance_id",
                "command_id",
                "operation_id",
                "agent_instance_id",
            ):
                event[key] = start[key]
            event["actual_descriptor"] = copy.deepcopy(start["descriptor"])
            assert (
                await video_control.event(
                    sn, wire.Ready.model_validate(event), service, send
                )
                is expected
            )

    if expected:
        record = await video_control.start(
            service, wire.Start.model_validate(start), 1, "owner", "session", send
        )
        assert record["state"] == "running"
        assert record["actual_descriptor"] == start["descriptor"]
        assert sent == ["stream_start"]
    else:
        with pytest.raises(HTTPException) as exc:
            await video_control.start(
                service, wire.Start.model_validate(start), 1, "owner", "session", send
            )
        assert exc.value.detail == {"code": "producer_lost"}
    assert lease.expires_at == before_deadline


@pytest.mark.anyio
@pytest.mark.parametrize(
    "case", ["over_budget", "lease_deadline", "old_media", "usb_camera"]
)
async def test_cold_start_extension_preserves_other_limits(native_env, case):
    service, lease, start, cap = native_env
    before_deadline = lease.expires_at
    start["expires_at_ms"] = start["issued_at_ms"] + 35000
    if case == "over_budget":
        start["expires_at_ms"] += 1
    elif case == "lease_deadline":
        start["lease_expires_at_ms"] = start["expires_at_ms"] - 1
    elif case == "old_media":
        del start["descriptor"]["contract_version"]
        start["descriptor"]["tracks"][0].update(width=1280, height=720, level_id=93)
    else:
        start["descriptor"]["source_type"] = "usb-camera"
        assert (
            select_codec(
                start,
                {
                    "authorized": True,
                    "tenant_matches": True,
                    "source_allowed": True,
                    "sn": lease.sn,
                    "lease_active": True,
                    "lease_id": str(lease.lease_id),
                },
            )
            == "invalid_payload"
        )
        return
    sender = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await video_control.start(
            service, wire.Start.model_validate(start), 1, "owner", "session", sender
        )
    assert exc.value.detail == {"code": "invalid_payload"}
    sender.assert_not_awaited()
    assert lease.expires_at == before_deadline
