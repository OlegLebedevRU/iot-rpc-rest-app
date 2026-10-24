"""Offline candidate oracle; never imported by product handlers."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import OrderedDict
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent
U64_MAX = (1 << 64) - 1
WIRE_MAX = (1 << 53) - 1


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def read(name):
    return json.loads(
        (ROOT / name).read_text(encoding="utf-8"), object_pairs_hook=unique_keys
    )


def add_tick(anchor, offset):
    if offset <= 0 or anchor < 0 or anchor > U64_MAX - offset:
        raise ValueError("arithmetic")
    return anchor + offset


def canonical_descriptor(value):
    """RFC8785 integer-only descriptor subset, not a general JCS serializer."""
    if value is None or type(value) is bool:
        return json.dumps(value)
    if type(value) is int and -WIRE_MAX <= value <= WIRE_MAX:
        return str(value)
    if isinstance(value, str):
        value.encode("utf-8")
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(canonical_descriptor(item) for item in value) + "]"
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        keys = sorted(value, key=lambda k: k.encode("utf-16-be"))
        return (
            "{"
            + ",".join(
                canonical_descriptor(k) + ":" + canonical_descriptor(value[k])
                for k in keys
            )
            + "}"
        )
    raise ValueError("descriptor_numeric_domain")


class Oracle:
    """One terminal across attempts/boots; separate server and device state.

    Initial query is already durably allocated and pending at server tick zero.
    Only authenticated control-plane actions change boot, binding or issuer.
    """

    def __init__(self, query, capacity=64):
        self.query = copy.deepcopy(query)
        self.binding = query["binding"]
        self.epoch = query["issuer_epoch"]
        self.server_seq = query["admission_seq"]
        self.pending = {"query": copy.deepcopy(query), "at": 0, "accepted": False}
        self.admission_hwm = 0
        self.token = self.active = None
        self.capacity = capacity
        self.readiness_cache = OrderedDict()
        self.receipts = OrderedDict()
        self.last_tick = self.start_count = 0
        self.clock_failed = False
        self.last_result = None

    def remember(self, cache, key, value):
        cache[key] = copy.deepcopy(value)
        while len(cache) > self.capacity:
            cache.popitem(last=False)

    def invalidate(self):
        self.active = self.token = self.pending = None

    def finish(self, message, outcome):
        self.last_result = outcome
        self.remember(self.receipts, message["command_id"], (message, outcome))
        return outcome

    def apply(self, event, message):
        action = event["action"]
        tick = event.get("tick", self.last_tick)
        self.last_result = None
        if action == "reboot":
            self.invalidate()
            self.binding = {**self.binding, "boot_id": event["boot_id"]}
            self.admission_hwm = self.server_seq = 0
            self.readiness_cache.clear()
            self.receipts.clear()
            self.clock_failed = False
            self.last_tick = tick
            return "invalidated"
        if tick < self.last_tick or tick > U64_MAX:
            self.invalidate()
            self.clock_failed = True
            return "clock_invalid"
        self.last_tick = tick
        if self.active and tick >= self.active["deadline"]:
            self.invalidate()
        if action in ("invalidate", "epoch_lost", "rebind"):
            self.invalidate()
            if action == "epoch_lost":
                self.epoch = event["issuer_epoch"]
            if action == "rebind":
                self.binding = event["binding"]
            return "invalidated"
        if self.clock_failed:
            return "clock_invalid"
        if message["sn"] != event.get("transport_sn", self.query["sn"]):
            return "transport_mismatch"
        if message["binding"] != self.binding or message["issuer_epoch"] != self.epoch:
            return "binding_mismatch"
        seq = message["admission_seq"]
        if action == "query":
            if seq <= self.server_seq:
                return "stale_server_sequence"
            if (
                self.pending
                and not self.pending["accepted"]
                and event["server_tick"] < self.pending["at"] + 5000
            ):
                return "pending_busy"
            self.server_seq = seq
            self.pending = {
                "query": copy.deepcopy(message),
                "at": event["server_tick"],
                "accepted": False,
            }
            return "query_pending"
        if action == "result":
            if not self.pending:
                return "no_pending"
            query = self.pending["query"]
            if any(
                message[k] != query[k]
                for k in (
                    "sn",
                    "binding",
                    "issuer_epoch",
                    "admission_seq",
                    "readiness_nonce",
                )
            ):
                return "wrong_nonce"
            if event["server_tick"] >= self.pending["at"] + 5000:
                return "pending_expired"
            if self.pending["accepted"]:
                return "result_replay"
            self.pending["accepted"] = True
            return "result_accepted"
        if action == "ready":
            if not 0 < message["expires_at_ms"] - message["issued_at_ms"] <= 5000:
                return "interval"
            if seq in self.readiness_cache:
                return (
                    "readiness_replay"
                    if self.readiness_cache[seq] == message
                    else "conflict"
                )
            if seq <= self.admission_hwm:
                return "stale_admission"
            if self.active:
                return "busy"
            self.admission_hwm = seq
            self.token = None
            self.token = {
                "query": copy.deepcopy(message),
                "r": tick,
                "until": add_tick(tick, 5000),
                "consumed": False,
            }
            self.remember(self.readiness_cache, seq, message)
            return "ready"
        if message["command_id"] in self.receipts:
            previous, outcome = self.receipts[message["command_id"]]
            if previous != message:
                return "conflict"
            self.last_result = outcome
            return "replay"
        if seq != self.admission_hwm or not self.token:
            return "stale_admission"
        query = self.token["query"]
        if message["readiness_nonce"] != query["readiness_nonce"]:
            return "wrong_nonce"
        if (
            not 0
            < message["expires_at_ms"] - message["issued_at_ms"]
            <= (5000 if action == "stop" else 60000)
        ):
            return "interval"
        if action == "start":
            if self.token["consumed"] or self.active:
                return "stale_command"
            self.token["consumed"] = True
            if tick >= self.token["until"]:
                return self.finish(message, "readiness_expired")
            if (
                not self.pending
                or not self.pending["accepted"]
                or self.pending["query"] != query
            ):
                return self.finish(message, "not_authorized")
            if message["source_id"] != self.binding["source_id"]:
                return self.finish(message, "binding_mismatch")
            issued = message["issued_at_ms"]
            deadline = add_tick(self.token["r"], message["expires_at_ms"] - issued)
            if tick >= deadline:
                self.invalidate()
                return self.finish(message, "expired")
            self.active = {
                "r": self.token["r"],
                "i": issued,
                "deadline": deadline,
                "last_issued": issued,
                "seq": 1,
                "start": copy.deepcopy(message),
            }
            self.start_count += 1
            return self.finish(message, "started")
        if not self.active:
            return "stale_command"
        state = self.active
        if any(
            message[k] != state["start"][k]
            for k in ("lease_id", "stream_instance_id", "readiness_nonce")
        ):
            return "identity_mismatch"
        if message["command_seq"] <= state["seq"]:
            return "stale_command"
        if message["issued_at_ms"] < state["last_issued"]:
            return "issuer_regression"
        deadline = add_tick(state["r"], message["expires_at_ms"] - state["i"])
        if tick >= deadline:
            return "expired"
        state.update(seq=message["command_seq"], last_issued=message["issued_at_ms"])
        if action == "stop":
            self.invalidate()
            return self.finish(message, "stopped")
        if deadline <= state["deadline"]:
            return self.finish(message, "not_extending")
        state["deadline"] = deadline
        return self.finish(message, "renewed")


def test_uuid(value):
    return f"00000000-0000-4000-8000-{value:012d}"


def verify_hashes():
    vectors = read("descriptor-hash-vectors.json")
    for vector in vectors["valid"]:
        value = json.loads(vector["input_json"], object_pairs_hook=unique_keys)
        canonical = canonical_descriptor(value).encode("utf-8")
        assert canonical.hex() == vector["canonical_utf8_hex"], vector["name"]
        assert canonical.decode("utf-8") == vector["canonical_json"], vector["name"]
        assert hashlib.sha256(canonical).hexdigest() == vector["sha256"], vector["name"]
    for vector in vectors["invalid"]:
        try:
            canonical_descriptor(
                json.loads(vector["input_json"], object_pairs_hook=unique_keys)
            ).encode("utf-8")
        except ValueError, UnicodeError:
            pass
        else:
            raise AssertionError(vector["name"])
    return {"valid": len(vectors["valid"]), "invalid": len(vectors["invalid"])}


def verify():
    schema = read("camera-ctl.schema.json")
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    vectors = read("vectors.json")
    messages = vectors["messages"]
    for message in messages.values():
        validator.validate(message)
        for field in message:
            changed = copy.deepcopy(message)
            del changed[field]
            assert not validator.is_valid(changed), (message["type"], "missing", field)
        for target in ((), ("binding",)):
            changed = copy.deepcopy(message)
            obj = changed
            for key in target:
                obj = obj[key]
            obj["unexpected"] = 1
            assert not validator.is_valid(changed), (message["type"], "unknown", target)
    for case in vectors["invalid_wire"]:
        changed = copy.deepcopy(messages[case["message"]])
        changed.update(case["patch"])
        assert not validator.is_valid(changed), case["name"]
    try:
        json.loads('{"v":1,"v":1}', object_pairs_hook=unique_keys)
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate JSON key accepted")
    steps = 0
    for case in vectors["cases"]:
        oracle = Oracle(messages["query"], case.get("capacity", 64))
        for event in case["events"]:
            message = copy.deepcopy(messages.get(event.get("message"), {}))
            message.update(event.get("patch", {}))
            if message:
                validator.validate(message)
            try:
                actual = oracle.apply(event, message)
            except ValueError as exc:
                actual = str(exc)
                oracle.invalidate()
            assert actual == event["expected"], (case["name"], event, actual)
            if "deadline" in event:
                assert oracle.active["deadline"] == event["deadline"], case["name"]
            if "saved_result" in event:
                assert oracle.last_result == event["saved_result"], case["name"]
            if "start_count" in event:
                assert oracle.start_count == event["start_count"], case["name"]
            if oracle.active:
                assert oracle.active["r"] == oracle.token["r"]
                assert oracle.active["i"] == oracle.active["start"]["issued_at_ms"]
            steps += 1
    for case in vectors["issuer_clock"]:
        exported = case["wall_ms0"] + case["monotonic_now"] - case["monotonic_ms0"]
        assert exported == case["expected_issued_at_ms"], case["name"]
    import runpy

    stress = runpy.run_path(str(ROOT / "stress.py"))["verify_stress"](
        vectors["stress"], messages, validator, Oracle
    )
    evidence = {
        "revision": vectors["revision"],
        "wire_examples": len(messages),
        "invalid_shapes": len(vectors["invalid_wire"]),
        "stateful_cases": len(vectors["cases"]),
        "stateful_steps": steps,
        "issuer_clock_cases": len(vectors["issuer_clock"]),
        "stress": stress,
        "descriptor_hash_vectors": verify_hashes(),
    }
    print("PASS: " + json.dumps(evidence, sort_keys=True))
    return evidence


if __name__ == "__main__":
    verify()
