"""Offline contract conformance oracle. Does not authorize or operate a stream."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent


def unique_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON key: {key}")
        value[key] = item
    return value


def read(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)


def digest_tree(root):
    files = {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name != "manifest.json" and "__pycache__" not in p.parts
    }
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return files, digest


def resolve_candidate(start, context):
    """Reference PREPARE decision only; h264 requires a new concrete descriptor."""
    if not context["authorized"]:
        return "unauthorized"
    if not context["tenant_matches"] or not context["source_allowed"] or start["sn"] != context["sn"]:
        return "forbidden"
    if not context["lease_active"]:
        return "lease_invalid"
    if start["lease_id"] != context["lease_id"]:
        return "lease_mismatch"
    if not 0 < start["expires_at_ms"] - start["issued_at_ms"] <= 30000:
        return "invalid_payload"
    if start["expires_at_ms"] > start["lease_expires_at_ms"]:
        return "invalid_payload"
    if not start["issued_at_ms"] <= context["now_ms"] < min(start["expires_at_ms"], start["lease_expires_at_ms"]):
        return "expired"
    active = context.get("active_start")
    if active:
        # Replay only after ownership checks. Command timing is not part of the descriptor.
        keys = ("lease_id", "stream_instance_id", "operation_id", "agent_instance_id",
                "resolved_codec", "descriptor", "delivery", "recovery_policy")
        return "already_running" if all(start[k] == active[k] for k in keys) else "conflict"
    if not context["negotiated_v2"]:
        return "unsupported"
    cap = context["capabilities"]
    if (start["agent_instance_id"] != context["agent_instance_id"]
            or cap["agent_instance_id"] != context["agent_instance_id"]
            or start["capability_revision"] != cap["capability_revision"]
            or start["descriptor"]["source_id"] != cap["source_id"]
            or start["descriptor"]["geometry_generation"] != cap["binding"]["geometry_generation"]
            or context["binding"] != cap["binding"]):
        return "capability_mismatch"
    policy = start["codec_policy"]
    if policy == "h264":
        return "h264"
    if (not 0 < cap["valid_until_ms"] - cap["checked_at_ms"] <= 60000
            or not cap["checked_at_ms"] <= context["now_ms"] < cap["valid_until_ms"]):
        return "h264" if policy == "auto" else "stale_capability"
    track = start["descriptor"]["tracks"][0]
    supported = context["server_hevc_ready"] and any(
        entry["codec"] == "h265" and entry["backend"] == "media_foundation"
        and entry["hardware"] and entry["status"] == "ready"
        and entry["probe_evidence"] == "encoded_sequence"
        and any(p["profile_id"] == start["descriptor"]["profile_id"] and p["track"] == track
                for p in entry["profiles"])
        for entry in cap["video"]
    )
    return "h265" if supported else "h264" if policy == "auto" else "unsupported"


def verify(iot_source=None):
    schema = read(ROOT / "hevc.schema.json")
    Draft202012Validator.check_schema(schema)
    count = 0
    mutations = 0
    for path in sorted((ROOT / "fixtures").glob("*.json")):
        fixture = read(path)
        selected = dict(schema, oneOf=[{"$ref": "#/$defs/" + fixture["definition"]}])
        valid = Draft202012Validator(selected, format_checker=FormatChecker()).is_valid(fixture["payload"])
        if valid != fixture["valid"]:
            errors = list(Draft202012Validator(selected, format_checker=FormatChecker()).iter_errors(fixture["payload"]))
            raise AssertionError(f"{path.name}: expected valid={fixture['valid']}: {errors[:1]}")
        assert len(json.dumps(fixture["payload"]).encode()) <= 32768
        if valid:
            def reject_unknown(value, path=()):
                nonlocal mutations
                if isinstance(value, dict):
                    changed = copy.deepcopy(fixture["payload"])
                    target = changed
                    for key in path:
                        target = target[key]
                    target["unrecognized_contract_field"] = None
                    assert not Draft202012Validator(selected, format_checker=FormatChecker()).is_valid(changed)
                    mutations += 1
                    for key, item in value.items():
                        reject_unknown(item, (*path, key))
                elif isinstance(value, list):
                    for index, item in enumerate(value):
                        reject_unknown(item, (*path, index))
            reject_unknown(fixture["payload"])
        count += 1
    try:
        json.loads('{"v":2,"v":1}', object_pairs_hook=unique_keys)
    except ValueError:
        pass
    else:
        raise AssertionError("Duplicate object key accepted")
    for scenario in read(ROOT / "scenarios.json"):
        actual = resolve_candidate(scenario["start"], scenario["context"])
        assert actual == scenario["expected"], (scenario["name"], actual, scenario["expected"])
    for case in read(ROOT / "lifecycle.json"):
        active = case["active"]
        if case.get("stale_stream"):
            event = copy.deepcopy(case["event"])
            event["stream_instance_id"] = "00000000-0000-4000-8000-000000000099"
        else:
            event = case["event"]
        action = case["action"]
        if action == "watcher_leave":
            outcome = "detach_only"
        elif action == "media_start":
            outcome = "replay" if case["request"] == active else "conflict"
        elif action == "ready":
            outcome = ("agent_ready_only" if case["ready"]["actual_descriptor"] == active["descriptor"]
                       else "descriptor_mismatch")
        elif event["stream_instance_id"] != active["publisher"]["stream_instance_id"]:
            outcome = "ignore"
        elif action == "stop":
            outcome = "stop_owned_publisher"
        else:
            outcome = "terminate_and_invalidate_capability"
        assert outcome == case["expected"], (case["name"], outcome)
    legacy_count = 0
    module = None
    if iot_source:
        spec = importlib.util.spec_from_file_location("hevc_legacy_models", Path(iot_source))
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    for path in sorted((ROOT / "legacy").glob("*.json")):
        if path.name.endswith((".schema.json", ".wire.json")):
            continue
        fixture = read(path)
        frozen = read(ROOT / "legacy" / (fixture["model"] + ".schema.json"))
        Draft202012Validator(frozen, format_checker=FormatChecker()).validate(fixture["payload"])
        if module:
            cls = getattr(module, fixture["model"])
            assert cls.model_json_schema() == frozen, f"legacy schema drift: {fixture['model']}"
            cls.model_validate(fixture["payload"])
        legacy_count += 1
    for name in ("h264_start", "stop"):
        assert read(ROOT / f"legacy/{name}.wire.json") == read(ROOT / f"legacy/{name}.json")["payload"]
    # Exact legacy projection: no error/descriptor/lease fields or new nulls.
    error = read(ROOT / "fixtures/runtime_error.json")["payload"]
    projected = {key: error[key] for key in ("type", "sn", "stream_instance_id", "state", "reason", "timestamp")}
    projected["v"] = 1
    assert projected == read(ROOT / "legacy/failed.json")["payload"]
    print(f"PASS: {count} schema fixtures, {legacy_count} legacy fixtures, "
          f"{len(read(ROOT / 'scenarios.json'))} PREPARE and {len(read(ROOT / 'lifecycle.json'))} lifecycle scenarios, "
          "exact v1 error projection")
    print(f"PASS: {mutations} unknown-property mutations rejected at every nested object; duplicate key rejected")
    if module:
        print("PASS: actual unchanged IoT v1 models accept fixtures and match frozen schemas")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iot-source", help="Path to unchanged remote_input/schemas.py; imports only DTO models")
    parser.add_argument("--expected-digest")
    parser.add_argument("--peer", action="append", type=Path, default=[])
    args = parser.parse_args()
    manifest = read(ROOT / "manifest.json")
    files, digest = digest_tree(ROOT)
    assert files == manifest["files"], "Contract file additions/removals/content drift"
    assert digest == manifest["sha256"], "Manifest digest mismatch"
    lock = read(ROOT.parent / "hevc-v2.lock.json")
    assert lock["sha256"] == digest and lock["revision"] == manifest["revision"], "Local lock drift"
    assert lock["sources"] == manifest["sources"], "Local source revision drift"
    if args.expected_digest:
        assert digest == args.expected_digest, "Frozen CI revision differs"
    for peer in args.peer:
        assert digest_tree(peer) == (files, digest), f"Cross-repository drift: {peer}"
    verify(args.iot_source)
    print(f"PASS: {manifest['revision']} sha256={digest}; peers={len(args.peer)}")


if __name__ == "__main__":
    main()
