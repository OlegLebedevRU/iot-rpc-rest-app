"""Pinned media/observation1.1 selection; observation is never authority."""

from __future__ import annotations

import copy
import hashlib
import json
from functools import lru_cache
from pathlib import Path

from jsonschema import FormatChecker
from referencing import Registry, Resource

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


MEDIA3 = "l4-media/3.0.0"
MEDIA12 = "siplite-camera/1.2.0"
ENROLLMENT03 = "camera-enrollment/0.3.0-proposed"
SELECTED3 = {
    "media_contract_revision": MEDIA3,
    "camera_contract_revision": MEDIA12,
    "cadence_revision": CADENCE,
    "enrollment_revision": ENROLLMENT03,
    "admission_revision": ADMISSION,
}
CAPABILITIES3 = {
    "media_contract_versions": [3],
    "camera_contract_revisions": [MEDIA12],
    "camera_cadence_revisions": [CADENCE],
    "camera_enrollment_revisions": [ENROLLMENT03],
    "camera_admission_revisions": [ADMISSION],
    "quality_options": [{"profile_id": "low"}, {"profile_id": "default"}],
}
SCHEMA12_SHA = "cba222ccdc2e10c446dc99e1bb0e2338d4fc08c28220f3bc02e8a8d391789194"
MEDIA3_SHA = "b86ca6f066fcdecb09cf7145a7fb23d87b77311a53c7ea04f0fb6e8a905b2818"
MEDIA13 = "siplite-camera/1.3.0"
CADENCE02 = "camera-cadence/0.2.0-proposed"
ENROLLMENT04 = "camera-enrollment/0.4.0-proposed"
SELECTED4 = {
    **SELECTED3,
    "camera_contract_revision": MEDIA13,
    "cadence_revision": CADENCE02,
    "enrollment_revision": ENROLLMENT04,
}
CAPABILITIES4 = {
    **CAPABILITIES3,
    "camera_contract_revisions": [MEDIA13],
    "camera_cadence_revisions": [CADENCE02],
    "camera_enrollment_revisions": [ENROLLMENT04],
}
SCHEMA13_SHA = "ed026e15251900f060b1a7550cb6e6f60c5c9631785979aef95fa11e713a446a"


def modern_selection(selection):
    return selection in (SELECTED3, SELECTED4)


def observation_validator(selection):
    if selection == SELECTED4:
        return validate13
    if selection == SELECTED3:
        return validate12
    if selection == SELECTED:
        return validate11
    raise ValueError("unsupported_camera_selection")


@lru_cache
def validator13(definition: str) -> StrictValidator:
    package = PACKAGE11.parent / "siplite-camera-v1.3"
    raw = (package / "camera.schema.json").read_bytes()
    manifest = json.loads((package / "manifest.json").read_text())
    if (
        hashlib.sha256(raw).hexdigest() != SCHEMA13_SHA
        or manifest["files"]["camera.schema.json"] != SCHEMA13_SHA
    ):
        raise ValueError("camera13_schema_pin_mismatch")
    schema = json.loads(raw)
    registry = Registry().with_resource(
        "urn:leo4:l4-media:3.0.0", Resource.from_contents(schema3())
    )
    return StrictValidator(
        {"$defs": schema["$defs"], "$ref": "#/$defs/" + definition},
        registry=registry,
        format_checker=FormatChecker(),
    )


def validate13(definition: str, value: dict, limit: int = 32768) -> dict:
    bounded_json(value, limit)
    if not validator13(definition).is_valid(value):
        raise ValueError("invalid_camera13_" + definition)
    return copy.deepcopy(value)


def headers4() -> dict:
    return {
        **headers3(),
        "X-L4-Camera-Contract": MEDIA13,
        "X-L4-Camera-Cadence": CADENCE02,
        "X-L4-Camera-Enrollment": ENROLLMENT04,
    }


@lru_cache
def schema3() -> dict:
    raw = (PACKAGE11.parent / "l4-media-v3/media.schema.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != MEDIA3_SHA:
        raise ValueError("camera_media3_schema_pin_mismatch")
    return json.loads(raw)


@lru_cache
def validator3(definition: str) -> StrictValidator:
    return StrictValidator(
        {"$defs": schema3()["$defs"], "$ref": "#/$defs/" + definition},
        format_checker=FormatChecker(),
    )


def validate3(definition: str, value: dict, limit: int = 32768) -> dict:
    bounded_json(value, limit)
    if not validator3(definition).is_valid(value):
        raise ValueError("invalid_camera_media3_" + definition)
    return copy.deepcopy(value)


@lru_cache
def schema12() -> dict:
    package = PACKAGE11.parent / "siplite-camera-v1.2"
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    raw = (package / "camera.schema.json").read_bytes()
    if (
        hashlib.sha256(raw).hexdigest() != SCHEMA12_SHA
        or manifest["files"]["camera.schema.json"] != SCHEMA12_SHA
    ):
        raise ValueError("camera12_schema_pin_mismatch")
    return json.loads(raw)


@lru_cache
def validator12(definition: str) -> StrictValidator:
    registry = Registry().with_resource(
        "urn:leo4:l4-media:3.0.0", Resource.from_contents(schema3())
    )
    return StrictValidator(
        {"$defs": schema12()["$defs"], "$ref": "#/$defs/" + definition},
        registry=registry,
        format_checker=FormatChecker(),
    )


def validate12(definition: str, value: dict, limit: int = 32768) -> dict:
    bounded_json(value, limit)
    if not validator12(definition).is_valid(value):
        raise ValueError("invalid_camera12_" + definition)
    return copy.deepcopy(value)


def headers3() -> dict:
    return {
        "X-L4-Media-Contract": MEDIA3,
        "X-L4-Camera-Contract": MEDIA12,
        "X-L4-Camera-Cadence": CADENCE,
        "X-L4-Camera-Enrollment": ENROLLMENT03,
        "X-L4-Camera-Admission": ADMISSION,
    }


def selection_for_descriptor(descriptor: dict) -> dict | None:
    if descriptor.get("contract_version") == 3:
        return copy.deepcopy(SELECTED3)
    if descriptor.get("camera_contract_revision") == MEDIA11:
        return copy.deepcopy(SELECTED)
    return None


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
    if any(
        headers.get(k) == v
        for k, v in (
            ("X-L4-Camera-Contract", MEDIA13),
            ("X-L4-Camera-Cadence", CADENCE02),
            ("X-L4-Camera-Enrollment", ENROLLMENT04),
        )
    ):
        if any(headers.get(k) != v for k, v in headers4().items()):
            raise ValueError("camera4_incomplete_revision_bundle")
        return copy.deepcopy(SELECTED4)
    if (
        headers.get("X-L4-Media-Contract") is not None
        or headers.get("X-L4-Camera-Contract") == MEDIA12
        or headers.get("X-L4-Camera-Enrollment") == ENROLLMENT03
    ):
        if any(headers.get(k) != v for k, v in headers3().items()):
            raise ValueError("camera3_incomplete_revision_bundle")
        return copy.deepcopy(SELECTED3)
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
    if revision in (MEDIA12, MEDIA13, MEDIA3) or (
        isinstance(value, dict) and value.get("contract_version") == 3
    ):
        return validate3(
            {"camera_descriptor": "descriptor", "camera_track": "track"}.get(
                definition, definition
            ),
            value,
            32768,
        )
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
