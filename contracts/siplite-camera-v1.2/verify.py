"""Offline exact camera1.2/common-media3 packet and cross-boundary vectors."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parent
MEDIA = ROOT.parent / "l4-media-v3/media.schema.json"
manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
assert hashlib.sha256(MEDIA.read_bytes()).hexdigest() == manifest["media_schema_sha256"]
for name, expected in manifest["files"].items():
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
schema = json.loads((ROOT / "camera.schema.json").read_text(encoding="utf-8"))
media = json.loads(MEDIA.read_text(encoding="utf-8"))
registry = Registry().with_resource(
    manifest["external_resource"], Resource.from_contents(media)
)


def validator(name):
    return Draft202012Validator(
        {**schema, "oneOf": [{"$ref": "#/$defs/" + name}]},
        registry=registry,
        format_checker=FormatChecker(),
    )


observation = json.loads(
    (ROOT / "example-observation.json").read_text(encoding="utf-8")
)
v = validator("camera_observation")
v.validate(observation)
v.validate(
    json.loads((ROOT / "example-h264-observation.json").read_text(encoding="utf-8"))
)
cases = 2
for field, value in [
    ("camera_contract_revision", "siplite-camera/1.1.0"),
    ("media_contract_revision", "l4-media/2.0.0"),
    ("cadence_revision", "unknown"),
    ("geometry_generation", -1),
    ("source_id", ""),
]:
    bad = copy.deepcopy(observation)
    bad[field] = value
    assert not v.is_valid(bad), field
    cases += 1
for field, value in [
    ("camera_enrollment_revisions", ["camera-enrollment/0.2.0-proposed"]),
    ("camera_contract_revisions", ["siplite-camera/1.1.0"]),
    ("media_contract_versions", [2]),
    ("quality_options", [{"profile_id": "native_auto"}]),
    ("quality_options", [{"profile_id": "low"}, {"profile_id": "low"}]),
]:
    bad = copy.deepcopy(observation)
    bad["capabilities"][field] = value
    assert not v.is_valid(bad), field
    cases += 1
for field, value in [
    ("fps", 0),
    ("width", 2593),
    ("codec_profile", "main10"),
    ("tier_flag", 1),
    ("max_b_frames", 1),
    ("repeat_parameter_sets", False),
    ("level_id", 154),
    ("cadence_revision", "camera-cadence/0.1.0-proposed"),
]:
    bad = copy.deepcopy(observation)
    bad["actual_track"][field] = value
    assert not v.is_valid(bad), field
    cases += 1
for field in schema["$defs"]["camera_observation"]["required"]:
    bad = copy.deepcopy(observation)
    del bad[field]
    assert not v.is_valid(bad), field
    cases += 1
for profile in ["low", "default"]:
    selected = copy.deepcopy(observation)
    selected["capabilities"]["quality_options"] = [{"profile_id": profile}]
    v.validate(selected)
    cases += 1
print(
    f"PASS camera1.2/common-media3 packet; {cases} positive/negative vectors; "
    "frozen media SHA verified"
)
