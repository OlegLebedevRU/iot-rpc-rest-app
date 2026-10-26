"""Candidate validation only: no MQTT publication, database, or camera writer."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from core.camera.quality_contract import (
    REVISION,
    CameraQualityReport,
    CameraQualitySet,
    QualityActual,
    QualityRequest,
    QualityTarget,
    camera_patch,
    command_deadline,
    protocol_schema,
)
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError


def command(**changes):
    value = dict(
        quality_revision=REVISION,
        sn="camera-test",
        command_id=uuid4(),
        lease_id=uuid4(),
        stream_instance_id=uuid4(),
        boot_id=uuid4(),
        issuer_epoch=uuid4(),
        admission_seq=2,
        generation=1,
        issued_at_ms=1000,
        expires_at_ms=1200,
        target=QualityTarget(target_bitrate_kbps=8000),
    )
    value.update(changes)
    return CameraQualitySet(**value)


@pytest.mark.parametrize("kbps", [0, 1, 99, 4001, 8000, 100000])
def test_bitrate_does_not_inherit_desktop_limits(kbps):
    assert camera_patch(QualityTarget(target_bitrate_kbps=kbps)) == {
        "video0": {"bitrate": kbps}
    }


@pytest.mark.parametrize(
    "size", ["", "2048x1536", "1920x1080", "2592x1944", "2304x1296"]
)
def test_sizes_are_not_a_halving_or_megapixel_whitelist(size):
    assert camera_patch(QualityTarget(size=size)) == {"video0": {"size": size}}


def test_native_auto_is_retained_without_rewriting_configuration():
    assert camera_patch(
        QualityTarget(size="", target_fps=0, target_bitrate_kbps=0)
    ) == {"video0": {"size": "", "fps": 0, "bitrate": 0}}


@pytest.mark.parametrize("value", [True, "8000", -1, 2**53])
def test_invalid_wire_integer(value):
    with pytest.raises(ValidationError):
        QualityTarget(target_bitrate_kbps=value)


@pytest.mark.parametrize(
    "target", [{}, {"target_fps": None}, {"universal_patch": {}}, {"size": "0x1080"}]
)
def test_invalid_or_empty_target(target):
    with pytest.raises(ValidationError):
        QualityTarget(**target)


def test_preset_and_codec_are_expressible_without_claiming_actuator_support():
    target = QualityTarget(
        preset_id="3MP", codec_policy="h265", target_bitrate_kbps=8000
    )
    with pytest.raises(ValueError, match="requires_source_resolution"):
        camera_patch(target)


def test_revision_is_explicit_and_writer_key_not_sent_to_source():
    request = QualityRequest(
        quality_revision=REVISION,
        stream_instance_id=uuid4(),
        writer_key=uuid4(),
        target=QualityTarget(target_bitrate_kbps=8000),
    )
    value = request.model_dump()
    del value["quality_revision"]
    with pytest.raises(ValidationError):
        QualityRequest(**value)
    with pytest.raises(ValidationError):
        command(writer_key=request.writer_key)


def test_deadline_clipped_to_original_remaining_lease():
    deadline = command_deadline(1000, remaining_lease_ms=200, command_budget_ms=5000)
    # Delivery at issuer coordinate1150 leaves50ms, not another200 or5000ms.
    assert deadline == 1200
    assert deadline - 1150 == 50
    assert deadline - 1250 < 0
    assert command(expires_at_ms=deadline).expires_at_ms == deadline


@pytest.mark.parametrize(
    "remaining,budget", [(0, 5000), (200, 0), (-1, 5000), (True, 5000)]
)
def test_exhausted_or_invalid_budget(remaining, budget):
    with pytest.raises(ValueError):
        command_deadline(1000, remaining, budget)


def test_deadline_cannot_overflow_or_reverse():
    with pytest.raises(ValueError):
        command_deadline(2**53 - 2, 10, 10)
    with pytest.raises(ValidationError):
        command(expires_at_ms=1000)


def test_source_can_reduce_and_restore_under_same_accepted_generation():
    cmd = command()
    base = {
        key: value
        for key, value in cmd.model_dump().items()
        if key not in ("type", "command_id", "issued_at_ms", "expires_at_ms", "target")
    }
    base.update(requested=cmd.target, status="limited", generation=cmd.generation)
    down = CameraQualityReport(
        **base,
        sample_seq=1,
        origin="source_pressure",
        actual=QualityActual(
            configured=QualityTarget(target_bitrate_kbps=4000),
            applied_bitrate_kbps=4000,
        ),
    )
    up = CameraQualityReport(
        **base,
        sample_seq=2,
        origin="source_recovery",
        actual=QualityActual(
            configured=QualityTarget(target_bitrate_kbps=6000),
            applied_bitrate_kbps=6000,
        ),
    )
    assert down.requested == up.requested == cmd.target
    assert down.generation == up.generation
    assert up.sample_seq > down.sample_seq
    assert up.actual.applied_bitrate_kbps > down.actual.applied_bitrate_kbps


def test_contract_can_express_fractional_fps_beyond_current_camera_actuator():
    target = QualityTarget(target_fps=29.97)
    assert target.target_fps == 29.97
    with pytest.raises(ValueError, match="native_integer_fps"):
        camera_patch(target)


def test_native_encoder_controls_are_explicit_not_an_arbitrary_patch():
    assert camera_patch(QualityTarget(rate_control="avbr", gop_seconds=1.5)) == {
        "video0": {"rcMode": "avbr", "gopSize": "1.5"}
    }


def test_unconfirmed_report_does_not_invent_actual_or_zero_metrics():
    cmd = command()
    base = {
        key: value
        for key, value in cmd.model_dump().items()
        if key not in ("type", "command_id", "issued_at_ms", "expires_at_ms", "target")
    }
    report = CameraQualityReport(
        **base,
        sample_seq=1,
        requested=cmd.target,
        status="unconfirmed",
        origin="initiator",
    )
    assert report.actual is None
    with pytest.raises(ValidationError):
        CameraQualityReport(**dict(report.model_dump(), status="applied"))
    with pytest.raises(ValidationError):
        QualityActual(configured=cmd.target, coded_width=1920)


def test_checked_schema_matches_models_and_accepts_non_desktop_target():
    root = Path(__file__).resolve().parents[4] / "contracts/runtime-quality-proposal"
    schema = json.loads((root / "schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(command().model_dump(mode="json", exclude_none=True))
    assert schema == protocol_schema()
