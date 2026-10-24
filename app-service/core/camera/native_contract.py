"""Pinned media/observation1.1 selection; observation is never authority."""

from __future__ import annotations

import copy
import hashlib
import json
from functools import lru_cache
from pathlib import Path

from jsonschema import FormatChecker

from core.camera.contract import (
    REVISION,
    StrictValidator,
    bounded_json,
    validate_definition,
)

MEDIA11 = "siplite-camera/1.1.0"
CADENCE = "camera-cadence/0.1.0-proposed"
ENROLLMENT02 = "camera-enrollment/0.2.0-proposed"
ADMISSION = "camera-ctl-monotonic/0.2.0-proposed"
SCHEMA_SHA = "bfd71ec96cf8de81657fd319c603f91a4769209887e32297fff4193752e3c62e"
PACKAGE11 = Path(__file__).resolve().parents[3] / "contracts/siplite-camera-v1.1"
SELECTED = {
    "camera_contract_revision": MEDIA11,
    "cadence_revision": CADENCE,
    "enrollment_revision": ENROLLMENT02,
    "admission_revision": ADMISSION,
}
CAPABILITIES = {
    "camera_contract_revisions": [MEDIA11],
    "camera_cadence_revisions": [CADENCE],
    "camera_enrollment_revisions": [ENROLLMENT02],
    "camera_admission_revisions": [ADMISSION],
}


@lru_cache
def schema11() -> dict:
    raw = (PACKAGE11 / "hevc.schema.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != SCHEMA_SHA:
        raise ValueError("camera11_schema_pin_mismatch")
    return json.loads(raw)


@lru_cache
def validator11(definition: str) -> StrictValidator:
    schema = schema11()
    return StrictValidator(
        {"$defs": schema["$defs"], "$ref": "#/$defs/" + definition},
        format_checker=FormatChecker(),
    )


def validate11(definition: str, value: dict, limit: int = 32768) -> dict:
    bounded_json(value, limit)
    if not validator11(definition).is_valid(value):
        raise ValueError("invalid_camera11_" + definition)
    return copy.deepcopy(value)


def selected_headers(headers) -> dict:
    actual = {
        "camera_contract_revision": headers.get("X-L4-Camera-Contract"),
        "cadence_revision": headers.get("X-L4-Camera-Cadence"),
        "enrollment_revision": headers.get("X-L4-Camera-Enrollment"),
        "admission_revision": headers.get("X-L4-Camera-Admission"),
    }
    if actual != SELECTED:
        raise ValueError("camera11_incomplete_revision_bundle")
    return copy.deepcopy(SELECTED)


def headers11() -> dict:
    return {
        "X-L4-Camera-Contract": MEDIA11,
        "X-L4-Camera-Cadence": CADENCE,
        "X-L4-Camera-Enrollment": ENROLLMENT02,
        "X-L4-Camera-Admission": ADMISSION,
    }


def validate_media(definition: str, value: dict, revision: str | None = None) -> dict:
    if revision is None:
        revision = (
            value.get("descriptor", {}).get("camera_contract_revision")
            if isinstance(value, dict)
            else None
        )
    if revision == MEDIA11:
        return validate11(definition, value)
    if revision == REVISION:
        return validate_definition("hevc.schema.json", definition, value)
    raise ValueError("unsupported_camera_media_revision")
