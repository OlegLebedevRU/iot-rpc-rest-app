"""Negotiated quality payloads; actual source capability selects implemented axes.

The existing desktop v1/v2 envelopes remain unchanged. Bounds below describe
JSON/wire representation, never a quality policy or a camera mode whitelist.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

REVISION = "l4-quality/1.0.0"
Integer = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]
Positive = Annotated[int, Field(strict=True, gt=0, le=2**53 - 1)]


class QualityTarget(BaseModel):
    """A partial target; omitted axes retain their last requested value.

    Zero bitrate/FPS and empty size mean native Auto. A preset supplies defaults;
    explicit axes override those defaults. Presets are not admissible-mode lists.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    target_bitrate_kbps: Integer | None = None
    target_fps: float | None = Field(
        default=None, strict=True, ge=0, allow_inf_nan=False
    )
    # Uses the native camera spelling, not a fixed list of megapixel presets.
    size: str | None = Field(default=None, pattern=r"^(?:|[1-9][0-9]*x[1-9][0-9]*)$")
    preset_id: str | None = Field(default=None, min_length=1)
    codec_policy: Literal["auto", "h264", "h265"] | None = None
    rate_control: str | None = Field(default=None, min_length=1)
    gop_seconds: float | None = Field(
        default=None, strict=True, gt=0, allow_inf_nan=False
    )

    @model_validator(mode="after")
    def nonempty(self) -> QualityTarget:
        if not self.model_dump(exclude_none=True):
            raise ValueError("quality_target_empty")
        return self


class QualityRequest(BaseModel):
    """Same original-writer proof and stream fence as desktop quality requests."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    quality_revision: Literal["l4-quality/1.0.0"]
    stream_instance_id: UUID
    writer_key: UUID
    target: QualityTarget


class CameraQualitySet(BaseModel):
    """Camera-specific adapter envelope on the existing CTL topic.

    issuer_epoch/admission_seq bind the active START; generation orders quality
    requests, independently of sample_seq. No writer credential reaches firmware.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    v: Literal[1] = 1
    type: Literal["stream_quality_set"] = "stream_quality_set"
    quality_revision: Literal["l4-quality/1.0.0"]
    sn: str = Field(min_length=1)
    command_id: UUID
    lease_id: UUID
    stream_instance_id: UUID
    boot_id: UUID
    issuer_epoch: UUID
    admission_seq: Positive
    generation: Positive
    issued_at_ms: Integer
    expires_at_ms: Integer
    target: QualityTarget

    @model_validator(mode="after")
    def positive_budget(self) -> CameraQualitySet:
        if self.expires_at_ms <= self.issued_at_ms:
            raise ValueError("quality_command_expired")
        return self


class QualityActual(BaseModel):
    """Confirmed encoder settings; observed traffic is not encoder target."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    configured: QualityTarget
    applied_bitrate_kbps: Integer | None = None
    coded_width: Positive | None = None
    coded_height: Positive | None = None
    nominal_fps: float | None = Field(
        default=None, strict=True, gt=0, allow_inf_nan=False
    )
    codec: Literal["h264", "h265"] | None = None

    @model_validator(mode="after")
    def complete_raster(self) -> QualityActual:
        if (self.coded_width is None) != (self.coded_height is None):
            raise ValueError("quality_raster_incomplete")
        return self


class CameraQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    v: Literal[1] = 1
    type: Literal["stream_quality_report"] = "stream_quality_report"
    quality_revision: Literal["l4-quality/1.0.0"]
    sn: str = Field(min_length=1)
    lease_id: UUID
    stream_instance_id: UUID
    boot_id: UUID
    issuer_epoch: UUID
    admission_seq: Positive
    sample_seq: Positive
    generation: Integer
    status: Literal["pending", "applied", "limited", "unsupported", "unconfirmed"]
    reason: str | None = None
    requested: QualityTarget
    actual: QualityActual | None = None
    # A local bitrate recovery uses the same accepted generation, a new sample.
    origin: Literal["initiator", "source_pressure", "source_recovery"]
    supported_targets: list[
        Literal[
            "target_bitrate_kbps",
            "size",
            "target_fps",
            "preset_id",
            "codec_policy",
            "rate_control",
            "gop_seconds",
        ]
    ] = Field(default_factory=list)
    bitrate_min_kbps: Integer | None = None
    bitrate_max_kbps: Positive | None = None
    persistence: Literal["camera_config", "volatile"] | None = None
    transport_pressure: bool | None = None

    @model_validator(mode="after")
    def confirmed_actual(self) -> CameraQualityReport:
        if self.status in ("applied", "limited") and self.actual is None:
            raise ValueError("quality_actual_required")
        return self


def camera_patch(target: QualityTarget) -> dict:
    """Project explicit supported axes only; do not turn presets into fixed modes.

    Resolution of named presets and live codec negotiation belongs to the source
    adapter. This helper deliberately cannot claim either operation was applied.
    """
    if target.preset_id is not None or target.codec_policy is not None:
        raise ValueError("quality_target_requires_source_resolution")
    names = {
        "target_bitrate_kbps": "bitrate",
        "target_fps": "fps",
        "size": "size",
        "rate_control": "rcMode",
        "gop_seconds": "gopSize",
    }
    patch = {
        names[key]: value for key, value in target.model_dump(exclude_none=True).items()
    }
    if "fps" in patch:
        if not patch["fps"].is_integer():
            raise ValueError("camera_native_integer_fps_required")
        patch["fps"] = int(patch["fps"])
    if "gopSize" in patch:
        patch["gopSize"] = str(patch["gopSize"])
    return {"video0": patch}


def command_deadline(
    issued: int, remaining_lease_ms: int, command_budget_ms: int
) -> int:
    """Called at the issuer, with its existing monotonic authority budget.

    Device receipt must compare this fixed coordinate to its enrolled R/I mapping;
    it must never derive a new deadline by adding TTL to arrival time.
    """
    for value in (issued, remaining_lease_ms, command_budget_ms):
        if type(value) is not int or not 0 <= value <= 2**53 - 1:
            raise ValueError("quality_budget_invalid")
    remaining = min(remaining_lease_ms, command_budget_ms)
    if remaining <= 0 or issued + remaining > 2**53 - 1:
        raise ValueError("quality_command_expired")
    return issued + remaining


def protocol_schema() -> dict:
    """Build the reviewable structural schema; models also check relationships."""
    definitions = {}
    models = (
        QualityTarget,
        QualityRequest,
        CameraQualitySet,
        QualityActual,
        CameraQualityReport,
    )
    for model in models:
        value = model.model_json_schema(ref_template="#/$defs/{model}")
        definitions.update(value.pop("$defs", {}))
        definitions[model.__name__] = value
    definitions["QualityTarget"]["anyOf"] = [
        {"required": [key], "properties": {key: {"not": {"type": "null"}}}}
        for key in QualityTarget.model_fields
    ]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:leo4:l4-quality:1.0.0",
        "title": "Candidate runtime quality extension (not media descriptor)",
        "$defs": definitions,
        "oneOf": [
            {"$ref": f"#/$defs/{model.__name__}"}
            for model in (QualityRequest, CameraQualitySet, CameraQualityReport)
        ],
    }
