"""Quality authority belongs to the original publisher, not other viewers."""

import copy
import hashlib
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from core.remote_input import video_models as wire
from core.remote_input.mqtt_bridge import handle_device_ctl_message
from core.remote_input.runtime_quality import (
    QualityReport,
    QualityRequest,
    runtime_quality,
)
from core.remote_input.video_control import now_ms, video_control
from fastapi import HTTPException

from . import test_video_v2 as fixtures

env = fixtures.env
native_env = fixtures.native_env


@pytest.mark.anyio
async def test_modern_software_h264_discovery_does_not_require_hevc_chain(
    native_env, monkeypatch
):
    from core.config import settings

    service, lease, start, cap = native_env
    monkeypatch.setattr(settings.remote_input, "video_hevc_chain_ready", False)
    h264 = fixtures.fixture("h264_v2_start")["descriptor"]["tracks"][0]
    cap["video"] = [
        {
            "codec": "h264",
            "backend": "openh264",
            "hardware": False,
            "status": "ready",
            "reason_code": None,
            "probe_evidence": "encoded_sequence",
            "profiles": [{"profile_id": "low", "track": h264}],
        }
    ]
    await video_control.store.change(lease.sn, lambda doc: doc.update(capability=cap))
    send = AsyncMock()
    result = await video_control.capability(
        lease.sn, service.presence, send, contract_version=3
    )
    assert result["negotiated_v2"] and result["video_capabilities"] == cap
    send.assert_not_awaited()
    start["resolved_codec"] = start["codec_policy"] = "h264"
    start["descriptor"]["tracks"] = [h264]

    async def dispatch(sn, command, **kwargs):
        assert command.type == "stream_start" and command.resolved_codec.value == "h264"
        assert await fixtures.ready_for(service, start)

    result = await video_control.start(
        service,
        wire.Start.model_validate(start),
        1,
        "owner",
        "session",
        AsyncMock(side_effect=dispatch),
    )
    assert (
        result["state"] == "running"
        and result["actual_descriptor"]["tracks"][0]["codec"] == "h264"
    )


async def running(native_env):
    service, lease, start, _ = native_env
    writer = uuid4()
    await video_control.store.change(
        lease.sn,
        lambda doc: doc.update(
            stream={
                "version": 2,
                "start": start,
                "state": "running",
                "org_id": 1,
                "owner_user_id": "owner",
                "owner_session_id": "session",
                "quality_writer_hash": hashlib.sha256(str(writer).encode()).hexdigest(),
            }
        ),
    )
    report = QualityReport(
        v=1,
        type="stream_quality_report",
        sn=lease.sn,
        lease_id=lease.lease_id,
        stream_instance_id=UUID(start["stream_instance_id"]),
        agent_instance_id=UUID(start["agent_instance_id"]),
        sample_seq=1,
        generation=0,
        applied_kbps=2000,
        status=0,
        transport_age_ms=20,
        delivery_kbps=1800,
        flags=5,
        raw_replaced=0,
    )
    assert await runtime_quality.report(lease.sn, report)
    request = QualityRequest(
        stream_instance_id=report.stream_instance_id,
        writer_key=writer,
        target_bitrate_kbps=1000,
    )
    return service, lease, report, request


@pytest.mark.anyio
async def test_raster_change_requires_opt_in_and_keeps_start_snapshot(native_env):
    service, lease, report, request = await running(native_env)
    send = AsyncMock()
    request = request.model_copy(update={"raster_step": 1, "target_bitrate_kbps": 500})
    with pytest.raises(HTTPException) as caught:
        await runtime_quality.set(
            service, lease.lease_id, 1, "owner", "session", request, send
        )
    assert caught.value.detail == {"code": "runtime_raster_unsupported"}
    send.assert_not_awaited()
    start = copy.deepcopy((await video_control.store.get(lease.sn))["stream"]["start"])
    track = start["descriptor"]["tracks"][0]
    extended = QualityReport.model_validate(
        dict(
            report.model_dump(exclude_none=True),
            sample_seq=2,
            quality_version=2,
            coded_width=track["width"],
            coded_height=track["height"],
            raster_step=0,
            ceiling_kbps=2000,
            last_idr_bytes=100000,
        )
    )
    assert await runtime_quality.report(lease.sn, extended)
    result = await runtime_quality.set(
        service, lease.lease_id, 1, "owner", "session", request, send
    )
    assert send.call_args.args[1].raster_step == 1
    state = await runtime_quality.get(lease.sn, str(request.stream_instance_id))
    assert state["status"] == "pending" and state["raster_step"] == 0
    assert not await runtime_quality.report(
        lease.sn,
        extended.model_copy(
            update={
                "sample_seq": 3,
                "generation": result["generation"],
                "applied_kbps": 500,
            }
        ),
    )
    applied = extended.model_copy(
        update={
            "sample_seq": 3,
            "generation": result["generation"],
            "applied_kbps": 500,
            "coded_width": (track["width"] >> 1) & ~1,
            "coded_height": (track["height"] >> 1) & ~1,
            "raster_step": 1,
            "last_idr_bytes": 20000,
        }
    )
    assert await runtime_quality.report(lease.sn, applied)
    state = await runtime_quality.get(lease.sn, str(request.stream_instance_id))
    assert (
        state["status"] == "limited"
        and state["raster_step"] == 1
        and state["last_idr_bytes"] == 20000
    )
    assert (await video_control.store.get(lease.sn))["stream"]["start"] == start


@pytest.mark.anyio
async def test_raster_report_cannot_change_capture_extent_or_raise_ceiling(native_env):
    _, lease, report, _ = await running(native_env)
    start = (await video_control.store.get(lease.sn))["stream"]["start"]
    track = start["descriptor"]["tracks"][0]
    extended = QualityReport.model_validate(
        dict(
            report.model_dump(exclude_none=True),
            sample_seq=2,
            quality_version=2,
            coded_width=(track["width"] >> 1) & ~1,
            coded_height=(track["height"] >> 1) & ~1,
            raster_step=1,
            ceiling_kbps=2000,
            last_idr_bytes=1000,
        )
    )
    for changes in ({"coded_width": track["width"] + 2}, {"ceiling_kbps": 4000}):
        assert not await runtime_quality.report(
            lease.sn, extended.model_copy(update=changes)
        )


def test_partial_raster_report_is_not_feature_advertisement():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="Incomplete raster quality report"):
        QualityReport.model_validate(
            dict(
                v=1,
                type="stream_quality_report",
                sn="test",
                lease_id=uuid4(),
                stream_instance_id=uuid4(),
                agent_instance_id=uuid4(),
                sample_seq=1,
                generation=0,
                applied_kbps=500,
                status=0,
                transport_age_ms=0,
                delivery_kbps=0,
                flags=1,
                raw_replaced=0,
                quality_version=2,
            )
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "user,session,org",
    [
        ("another", "session", 1),
        ("owner", "other-tab", 1),
        ("owner", "session", 2),
        ("", "session", 1),
        ("owner", "", 1),
    ],
)
async def test_other_viewer_cannot_control(native_env, user, session, org):
    service, lease, _, request = await running(native_env)
    send = AsyncMock()
    with pytest.raises(HTTPException) as caught:
        await runtime_quality.set(
            service, lease.lease_id, org, user, session, request, send
        )
    assert caught.value.status_code == 403
    send.assert_not_awaited()


@pytest.mark.anyio
async def test_changed_current_owner_does_not_inherit_original_publisher(native_env):
    service, lease, _, request = await running(native_env)
    lease.owner_user_id, lease.owner_session_id = "new-owner", "new-session"
    send = AsyncMock()
    with pytest.raises(HTTPException) as caught:
        await runtime_quality.set(
            service, lease.lease_id, 1, "new-owner", "new-session", request, send
        )
    assert caught.value.status_code == 403
    send.assert_not_awaited()


@pytest.mark.anyio
async def test_same_login_in_another_tab_cannot_claim_quality_writer(native_env):
    service, lease, _, request = await running(native_env)
    send = AsyncMock()
    with pytest.raises(HTTPException) as caught:
        await runtime_quality.set(
            service,
            lease.lease_id,
            1,
            "owner",
            "session",
            request.model_copy(update={"writer_key": uuid4()}),
            send,
        )
    assert caught.value.status_code == 403
    send.assert_not_awaited()
    view = await runtime_quality.get(lease.sn, str(request.stream_instance_id))
    assert not any("writer" in key for key in view)


@pytest.mark.anyio
async def test_only_initial_start_binds_writer_and_duplicate_cannot_replace_it(
    native_env,
):
    service, _lease, start, _ = native_env
    writer = uuid4()

    async def send(sn, command, **kwargs):
        if command.type == "stream_start":
            assert await fixtures.ready_for(service, start)

    sender = AsyncMock(side_effect=send)
    first = await video_control.start(
        service,
        wire.Start.model_validate(start),
        1,
        "owner",
        "session",
        sender,
        quality_writer_key=writer,
    )
    assert first["state"] == "running"
    original_hash = hashlib.sha256(str(writer).encode()).hexdigest()
    assert first["quality_writer_hash"] == original_hash
    repeated = await video_control.start(
        service,
        wire.Start.model_validate(start),
        1,
        "owner",
        "session",
        sender,
        quality_writer_key=uuid4(),
    )
    assert repeated["result"] == "already_running"
    assert repeated["quality_writer_hash"] == original_hash
    assert sender.await_count == 1


@pytest.mark.anyio
async def test_http_start_binds_private_writer_header_without_changing_ctl(
    native_env, monkeypatch
):
    from api.internal_v1 import remote_input as api
    from core.config import settings
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    service, lease, start, _ = native_env
    writer = uuid4()
    sent = []

    async def send(sn, command, **kwargs):
        sent.append(command.model_dump(mode="json"))
        if command.type == "stream_start":
            assert await fixtures.ready_for(service, start)

    monkeypatch.setattr(api, "remote_input_service", service)
    monkeypatch.setattr(api, "send_ctl_command", send)
    monkeypatch.setattr(settings.auth, "internal_service_key", "test-secret")
    application = FastAPI()
    application.include_router(api.router)
    headers = {
        "X-Internal-Service-Key": "test-secret",
        "X-Org-Id": "1",
        "X-User-Id": "owner",
        "X-Session-Id": "session",
        "X-Role": "user",
        "X-L4-Media-Contract": "l4-media/3.0.0",
        "X-Video-Quality-Writer": str(writer),
    }
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
        headers=headers,
    ) as client:
        start.update(issued_at_ms=now_ms(), expires_at_ms=now_ms() + 2000)
        result = await client.post(
            f"{api.router.prefix}/lease/{lease.lease_id}/stream/start", json=start
        )
    assert result.status_code == 200, result.text
    assert str(writer) not in result.text and str(writer) not in str(sent)
    record = (await video_control.store.get(lease.sn))["stream"]
    assert (
        record["quality_writer_hash"]
        == hashlib.sha256(str(writer).encode()).hexdigest()
    )


@pytest.mark.anyio
async def test_ack_is_not_applied_and_report_is_epoch_and_generation_bound(native_env):
    service, lease, report, request = await running(native_env)
    send = AsyncMock()
    result = await runtime_quality.set(
        service, lease.lease_id, 1, "owner", "session", request, send
    )
    assert result["generation"] == 1
    command = send.call_args.args[1]
    ack = {
        "v": 1,
        "type": "ack",
        "sn": lease.sn,
        "lease_id": str(lease.lease_id),
        "command_id": result["command_id"],
        "result": "accepted",
        "stream_instance_id": str(request.stream_instance_id),
    }
    assert await runtime_quality.reply(lease.sn, ack)
    state = await runtime_quality.get(lease.sn, str(request.stream_instance_id))
    assert state["status"] == "pending" and state["applied_kbps"] == 2000
    assert command.target_bitrate_kbps == 1000
    applied = report.model_copy(
        update={"sample_seq": 2, "generation": 1, "applied_kbps": 1000}
    )
    assert await runtime_quality.report(lease.sn, applied)
    assert not await runtime_quality.report(lease.sn, report)
    for field in ("stream_instance_id", "lease_id", "agent_instance_id"):
        assert not await runtime_quality.report(
            lease.sn, applied.model_copy(update={field: uuid4(), "sample_seq": 3})
        )
    assert not await runtime_quality.report("another-terminal", applied)
    state = await runtime_quality.get(lease.sn, str(request.stream_instance_id))
    assert state["status"] == "limited" and state["applied_kbps"] == 1000
    assert not await runtime_quality.reply(
        lease.sn, dict(ack, stream_instance_id=str(uuid4()))
    )


@pytest.mark.anyio
async def test_legacy_source_needs_no_quality_support_for_running_stream(native_env):
    service, lease, _, request = await running(native_env)
    await video_control.store.change(lease.sn, lambda doc: doc.pop("runtime_quality"))
    send = AsyncMock()
    assert await runtime_quality.get(lease.sn, str(request.stream_instance_id)) == {
        "available": False
    }
    with pytest.raises(HTTPException) as caught:
        await runtime_quality.set(
            service, lease.lease_id, 1, "owner", "session", request, send
        )
    assert caught.value.detail == {"code": "runtime_quality_unsupported"}
    assert (await video_control.store.get(lease.sn))["stream"]["state"] == "running"
    send.assert_not_awaited()


@pytest.mark.anyio
async def test_publish_failure_does_not_claim_encoder_changed(native_env):
    service, lease, _, request = await running(native_env)
    with pytest.raises(HTTPException) as caught:
        await runtime_quality.set(
            service,
            lease.lease_id,
            1,
            "owner",
            "session",
            request,
            AsyncMock(side_effect=OSError("offline")),
        )
    assert caught.value.status_code == 503
    state = await runtime_quality.get(lease.sn, str(request.stream_instance_id))
    assert state["status"] == "unconfirmed" and state["applied_kbps"] == 2000


@pytest.mark.anyio
async def test_old_stream_and_above_profile_cannot_publish(native_env):
    service, lease, _, request = await running(native_env)
    send = AsyncMock()
    for invalid in (
        request.model_copy(update={"stream_instance_id": uuid4()}),
        request.model_copy(update={"target_bitrate_kbps": 4000}),
    ):
        with pytest.raises(HTTPException):
            await runtime_quality.set(
                service, lease.lease_id, 1, "owner", "session", invalid, send
            )
    send.assert_not_awaited()


@pytest.mark.anyio
async def test_report_from_next_agent_cannot_reset_sequence_for_live_stream(native_env):
    _, lease, report, _ = await running(native_env)
    doc = copy.deepcopy(await video_control.store.get(lease.sn))
    assert not await runtime_quality.report(
        lease.sn,
        report.model_copy(
            update={
                "agent_instance_id": uuid4(),
                "sample_seq": 999,
                "applied_kbps": 100,
            }
        ),
    )
    assert await video_control.store.get(lease.sn) == doc


@pytest.mark.anyio
async def test_mqtt_report_and_ack_use_the_existing_agent_connection(native_env):
    service, lease, report, request = await running(native_env)
    sent = AsyncMock()
    result = await runtime_quality.set(
        service, lease.lease_id, 1, "owner", "session", request, sent
    )
    route = f"dev.{lease.sn}.ctl"
    assert await handle_device_ctl_message(
        routing_key=route,
        payload={
            "v": 1,
            "type": "ack",
            "sn": lease.sn,
            "lease_id": str(lease.lease_id),
            "command_id": result["command_id"],
            "result": "accepted",
            "stream_instance_id": str(request.stream_instance_id),
        },
    )
    assert await handle_device_ctl_message(
        routing_key=route,
        payload=report.model_copy(
            update={"sample_seq": 2, "generation": 1, "applied_kbps": 1000}
        ).model_dump(mode="json"),
    )
    state = await runtime_quality.get(lease.sn, str(report.stream_instance_id))
    assert state["applied_kbps"] == 1000 and state["generation"] == 1
    assert not await runtime_quality.report(
        lease.sn,
        report.model_copy(
            update={"sample_seq": 3, "generation": 2, "applied_kbps": 100}
        ),
    )


@pytest.mark.anyio
async def test_input_ack_does_not_query_the_quality_transaction(monkeypatch):
    receiver = AsyncMock(
        side_effect=AssertionError("Input ACK must not enter quality plane")
    )
    monkeypatch.setattr(runtime_quality, "reply", receiver)
    await handle_device_ctl_message(
        routing_key="dev.fixture.ctl",
        payload={
            "v": 1,
            "type": "ack",
            "sn": "fixture",
            "command_id": str(uuid4()),
            "lease_id": str(uuid4()),
            "result": "injected",
        },
    )
    receiver.assert_not_awaited()
