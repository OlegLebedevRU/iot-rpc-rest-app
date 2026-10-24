"""Offline schema/canonical checks; never reads cameras or grants authority."""
import copy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).parent
schema = json.loads((ROOT / "hevc.schema.json").read_text())
manifest = json.loads((ROOT / "manifest.json").read_text())
vectors = json.loads((ROOT / "canonical-vectors.json").read_text())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def valid(definition, value):
    return Draft202012Validator(
        dict(schema, oneOf=[{"$ref": f"#/$defs/{definition}"}]),
        format_checker=FormatChecker(),
    ).is_valid(value)


def main():
    assert hashlib.sha256((ROOT / "hevc.schema.json").read_bytes()).hexdigest() == manifest["schema_sha256"]
    assert hashlib.sha256((ROOT.parent / "siplite-camera-v1/hevc.schema.json").read_bytes()).hexdigest() == manifest["baseline_media_sha256"]
    for name in ("descriptor", "binding"):
        assert canonical(vectors[name]) == vectors[name + "_canonical"]
        assert hashlib.sha256(canonical(vectors[name]).encode()).hexdigest() == vectors[name + "_sha256"]
    assert valid("camera_descriptor", vectors["descriptor"])
    assert valid("camera_observation", vectors["observation"])
    for field in ("cadence_revision", "camera_contract_revision"):
        changed = copy.deepcopy(vectors["descriptor"])
        changed[field] = "unsupported"
        assert not valid("camera_descriptor", changed)
        assert hashlib.sha256(canonical(changed).encode()).hexdigest() != vectors["descriptor_sha256"]
        del changed[field]
        assert not valid("camera_descriptor", changed)
    for field in vectors["observation"]["capabilities"]:
        changed = copy.deepcopy(vectors["observation"])
        del changed["capabilities"][field]
        assert not valid("camera_observation", changed)
    old = json.loads((ROOT.parent / "siplite-camera-v1/hevc.schema.json").read_text())
    assert not Draft202012Validator(dict(old, oneOf=[{"$ref": "#/$defs/camera_descriptor"}])).is_valid(vectors["descriptor"])
    print("PASS: schema SHA, frozen baseline, canonical hashes, full bundle and negative policy vectors")


if __name__ == "__main__":
    main()
