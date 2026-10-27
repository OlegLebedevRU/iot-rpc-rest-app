"""Real issuer state/outbox and Redis report ordering; no production services."""

import copy
from uuid import uuid4

import pytest
from core.camera.quality import camera_quality
from core.camera.quality_contract import CameraQualityReport, REVISION
from core.camera.native_contract import validator3
from core.remote_input.video_control import video_control

from ..services import test_camera_runtime as runtime_fixtures
from ..services.test_camera_media3 import configured as media3_configuration
from ..services.test_camera_negotiated import epoch_and_lease


@pytest.fixture
def environment(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings.camera, "quality_sn_allowlist", [runtime_fixtures.SN])
    return runtime_fixtures.environment.__wrapped__(monkeypatch)


def test_start_only_exception_does_not_enable_physical_quality_writes(monkeypatch):
    from core.config import settings
    from core.camera.quality_policy import quality_enabled

    monkeypatch.setattr(settings.camera, "writers_enabled", False)
    monkeypatch.setattr(settings.camera, "test_start_sn_allowlist", ["scope"])
    monkeypatch.setattr(settings.camera, "quality_sn_allowlist", [])
    assert not quality_enabled("scope")
    monkeypatch.setattr(settings.camera, "quality_sn_allowlist", ["scope"])
    assert quality_enabled("scope") and not quality_enabled("other")


@pytest.mark.anyio
async def test_quality_issuer_clips_to_old_deadline_despite_utc_jump(environment):
    e = environment
    await runtime_fixtures.enroll(e)
    value, start = await runtime_fixtures.start(e)
    e.clock.advance(59000)
    e.clock.wall += 3600000
    request = {
        **value,
        "generation": 1,
        "command_id": str(uuid4()),
        "target": {"target_bitrate_kbps": 8000},
    }
    quality = await e.runtime.submit(runtime_fixtures.SN, "quality", request)
    assert quality["issued_at_ms"] == start["issued_at_ms"] + 59000
    assert quality["expires_at_ms"] == start["issued_at_ms"] + 60000
    assert e.sent[-1] == quality
    assert quality["boot_id"] == start["binding"]["boot_id"]
    before = e.store.row.state["active"]["quality_generation"]
    with pytest.raises(ValueError, match="quality_stale"):
        await e.runtime.submit(runtime_fixtures.SN, "quality", request)
    assert e.store.row.state["active"]["quality_generation"] == before
    e.clock.advance(1000)
    with pytest.raises(ValueError, match="stream_not_live"):
        await e.runtime.submit(
            runtime_fixtures.SN, "quality", {**request, "generation": 2}
        )


@pytest.mark.anyio
async def test_quality_wrong_stream_and_retirement_never_publish(environment):
    e = environment
    await runtime_fixtures.enroll(e)
    value, _ = await runtime_fixtures.start(e)
    sent = len(e.sent)
    with pytest.raises(ValueError, match="stream_not_live"):
        await e.runtime.submit(
            runtime_fixtures.SN,
            "quality",
            {
                **value,
                "stream_instance_id": str(uuid4()),
                "generation": 1,
                "target": {"target_bitrate_kbps": 8000},
            },
        )
    await e.runtime.submit(runtime_fixtures.SN, "retire", value)
    with pytest.raises(ValueError, match="stream_not_live"):
        await e.runtime.submit(
            runtime_fixtures.SN,
            "quality",
            {
                **value,
                "generation": 1,
                "target": {"target_bitrate_kbps": 8000},
            },
        )
    assert len(e.sent) == sent


@pytest.fixture
async def report_fixture():
    sn = "camera-quality-report-" + uuid4().hex
    lease, stream, boot, issuer = (str(uuid4()) for _ in range(4))
    authority = {"boot_id": boot, "issuer_epoch": issuer, "admission_seq": 1}
    old, _ = epoch_and_lease()
    start = {
        **old.start,
        "contract_version": 3,
        "descriptor": media3_configuration()["descriptor"],
    }
    start.update(lease_id=lease)
    start["publisher"].update(sn=sn, stream_instance_id=stream)
    errors = list(validator3("media_start").iter_errors(start))
    assert not errors, [(list(error.path), error.message) for error in errors]
    record = {
        "state": "running",
        "quality_authority": authority,
        "start": start,
    }
    report = {
        "v": 1,
        "type": "stream_quality_report",
        "quality_revision": REVISION,
        "sn": sn,
        "lease_id": lease,
        "stream_instance_id": stream,
        **authority,
        "sample_seq": 1,
        "generation": 0,
        "status": "applied",
        "origin": "initiator",
        "requested": {"target_bitrate_kbps": 0},
        "actual": {
            "configured": {"target_bitrate_kbps": 0},
            "applied_bitrate_kbps": 5000,
            "codec": "h265",
        },
        "supported_targets": ["target_bitrate_kbps"],
        "bitrate_min_kbps": 0,
        "bitrate_max_kbps": 20000,
        "persistence": "camera_config",
        "transport_pressure": False,
    }
    try:
        yield sn, record, report
    finally:
        await video_control.store.change(sn, lambda doc: doc.pop("camera_stream", None))


@pytest.mark.anyio
@pytest.mark.parametrize(
    "field",
    [
        "boot_id",
        "issuer_epoch",
        "lease_id",
        "stream_instance_id",
        "sn",
        "admission_seq",
    ],
)
async def test_report_rejects_foreign_attempt_and_preserves_current_sample(
    report_fixture, field
):
    sn, record, raw = report_fixture
    await video_control.store.change(sn, lambda doc: doc.update(camera_stream=record))
    assert await camera_quality.report(sn, CameraQualityReport(**raw))
    bad = dict(raw, sample_seq=2)
    bad[field] = 2 if field == "admission_seq" else str(uuid4())
    assert not await camera_quality.report(sn, CameraQualityReport(**bad))
    assert (await video_control.store.get(sn))["camera_stream"]["quality_report"][
        "sample_seq"
    ] == 1


@pytest.mark.anyio
async def test_source_down_and_recovery_keep_target_and_do_not_claim_new_generation(
    report_fixture,
):
    sn, record, raw = report_fixture
    await video_control.store.change(sn, lambda doc: doc.update(camera_stream=record))
    assert await camera_quality.report(sn, CameraQualityReport(**raw))
    down = copy.deepcopy(raw)
    down.update(sample_seq=2, origin="source_pressure", status="limited")
    down["actual"].update(
        configured={"target_bitrate_kbps": 2000}, applied_bitrate_kbps=2000
    )
    assert await camera_quality.report(sn, CameraQualityReport(**down))
    up = copy.deepcopy(down)
    up.update(sample_seq=3, origin="source_recovery")
    up["actual"].update(
        configured={"target_bitrate_kbps": 3000}, applied_bitrate_kbps=3000
    )
    assert await camera_quality.report(sn, CameraQualityReport(**up))
    assert not await camera_quality.report(sn, CameraQualityReport(**down))
    actual = await camera_quality.get(sn, raw["stream_instance_id"])
    assert actual["applied_kbps"] == 3000 and actual["requested_kbps"] == 0
    assert actual["ceiling_kbps"] == 5000 and actual["generation"] == 0


@pytest.mark.anyio
async def test_quality_rechecks_original_lease_owner_before_publication(environment):
    e = environment
    await runtime_fixtures.enroll(e)
    value, _ = await runtime_fixtures.start(e)
    seen = []

    async def authority(sn, payload):
        seen.append(dict(payload))
        if len(seen) > 1:
            assert payload["owner_user_id"] == "original-user"
            assert payload["owner_session_id"] == "original-session"
            raise ValueError("camera_lease_owner_changed")
        return 60000

    e.runtime.authority = authority
    sent = len(e.sent)
    await e.runtime.submit(
        runtime_fixtures.SN,
        "quality",
        {
            **value,
            "generation": 1,
            "command_id": str(uuid4()),
            "owner_user_id": "original-user",
            "owner_session_id": "original-session",
            "target": {"target_bitrate_kbps": 1000},
        },
    )
    assert len(seen) == 2 and len(e.sent) == sent
    assert not e.store.row.state["outbox"]
