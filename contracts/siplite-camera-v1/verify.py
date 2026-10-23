"""Offline schema, compatibility, Auto-selection and credential-envelope checks."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import rsa
from jsonschema import Draft202012Validator, FormatChecker

from credential_reference import seal, unseal

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "hevc-v2"


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


def validator(schema, definition):
    selected = dict(schema, oneOf=[{"$ref": "#/$defs/" + definition}])
    return Draft202012Validator(selected, format_checker=FormatChecker())


def resolve_auto(policy, capabilities, phase="pre_start", authorized=True):
    if not authorized:
        return "unauthorized"
    if phase != "pre_start":
        return "stream_immutable"
    if policy not in ("auto", "h264", "h265"):
        return "invalid_policy"
    requested = ("h265", "h264") if policy == "auto" else (policy,)
    for codec in requested:
        states = [stage[codec] for stage in capabilities]
        if all(state == "ready" for state in states):
            return codec
        if any(state not in ("ready", "unsupported") for state in states):
            return "capability_pending"
        if policy != "auto":
            return "unsupported"
    return "unsupported"


def verify():
    names = {"media": "hevc.schema.json", "rpc": "camera-rpc.schema.json", "local": "local-camera.schema.json"}
    schemas = {key: read(ROOT / name) for key, name in names.items()}
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
    count = 0
    unknown_mutations = 0
    for path in sorted((ROOT / "fixtures").glob("*.json")):
        case = read(path)
        check = validator(schemas[case["target"]], case["definition"])
        errors = list(check.iter_errors(case["payload"]))
        assert (not errors) == case["valid"], (path.name, [err.message for err in errors[:1]])
        assert len(json.dumps(case["payload"]).encode()) <= 32768
        if case["valid"]:
            def reject_unknown(value, path=()):
                nonlocal unknown_mutations
                if isinstance(value, dict):
                    changed = copy.deepcopy(case["payload"])
                    target = changed
                    for key in path:
                        target = target[key]
                    target["unexpected_contract_field"] = True
                    assert not check.is_valid(changed), (case["name"], path)
                    unknown_mutations += 1
                    for key, item in value.items():
                        reject_unknown(item, (*path, key))
                elif isinstance(value, list):
                    for index, item in enumerate(value):
                        reject_unknown(item, (*path, index))
            reject_unknown(case["payload"])
        count += 1
    baseline = read(BASE / "hevc.schema.json")
    for key in ("h264_track", "h265_track", "track", "probe_binding", "capabilities", "start", "ready"):
        assert schemas["media"]["$defs"][key] == baseline["$defs"][key], key
    old_count = 0
    for path in sorted((BASE / "fixtures").glob("*.json")):
        case = read(path)
        assert validator(schemas["media"], case["definition"]).is_valid(case["payload"]) == case["valid"], path.name
        old_count += 1
    ready = [{"h264": "ready", "h265": "ready"} for _ in range(4)]
    assert resolve_auto("auto", ready) == "h265"
    unavailable = copy.deepcopy(ready); unavailable[2]["h265"] = "unsupported"
    assert resolve_auto("auto", unavailable) == "h264"
    assert resolve_auto("h265", unavailable) == "unsupported"
    unknown = copy.deepcopy(ready); unknown[0]["h265"] = "unknown"
    assert resolve_auto("auto", unknown) == "capability_pending"
    assert resolve_auto("auto", ready, phase="running") == "stream_immutable"
    assert resolve_auto("auto", ready, authorized=False) == "unauthorized"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = 1800000000000
    metadata = {"sn": "camera-fixture", "operation_id": "00000000-0000-4000-8000-000000000011",
                "recipient_cert_sha256": "a" * 64, "expires_at_ms": now + 45000}
    plaintext = {"username": "synthetic-user", "password": "synthetic-only"}
    envelope = seal(key.public_key(), plaintext, metadata, now)
    assert validator(schemas["rpc"], "sealed_credentials").is_valid(envelope)
    binding = {key: metadata[key] for key in ("sn", "operation_id", "recipient_cert_sha256")}
    assert unseal(key, envelope, **binding, now_ms=now) == plaintext
    negative_crypto = 0
    for field in ("sn", "operation_id", "recipient_cert_sha256", "expires_at_ms", "tag", "wrapped_key", "ciphertext"):
        changed = dict(envelope)
        changed[field] = now - 1 if field == "expires_at_ms" else "different" if field in binding else "AAAA"
        try:
            unseal(key, changed, **binding, now_ms=now)
        except Exception:
            negative_crypto += 1
        else:
            raise AssertionError("tamper accepted: " + field)
    # Validate the complete cloud payload, never only its inner cryptographic header.
    payload = {"dt": [{"action": "set_credentials", "operation_id": metadata["operation_id"],
                       "expected_revision": "b" * 64, "sealed_credentials": envelope}]}
    assert validator(schemas["rpc"], "rpc166").is_valid(payload)
    assert "synthetic-only" not in json.dumps(payload)
    manifest_path = ROOT / "manifest.json"
    if manifest_path.exists():
        manifest = read(manifest_path)
        actual = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in ROOT.rglob("*") if p.is_file() and p.name != "manifest.json"
                  and "__pycache__" not in p.parts}
        assert actual == manifest["files"], "Contract file set/content drift"
        digest = hashlib.sha256(json.dumps(actual, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        assert digest == manifest["sha256"], "Contract aggregate drift"
        lock = read(ROOT.parent / "siplite-camera-v1.lock.json")
        assert all(lock[key] == manifest[key] for key in lock), "Contract lock drift"
        for name, digest in manifest["files"].items():
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
    print(json.dumps({"camera_fixtures": count, "unchanged_baseline_fixtures": old_count,
                      "unknown_field_mutations": unknown_mutations,
                      "auto_policy_checks": 6, "credential_tamper_checks": negative_crypto,
                      "credential_roundtrip": True, "runtime_verified": False}))


if __name__ == "__main__":
    verify()
