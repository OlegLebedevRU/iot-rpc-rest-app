"""Bounded replay-cache stress on one terminal model, without resets."""

import copy
import json


def uuid(value):
    return f"00000000-0000-4000-8000-{value:012d}"


def verify_stress(spec, messages, validator, oracle_type):
    validators = {
        name: validator.evolve(
            schema={**validator.schema, "oneOf": [{"$ref": "#/$defs/" + name}]}
        )
        for name in ("query", "result", "start", "renew", "stop")
    }
    validated = set()

    def apply(oracle, action, tick, message, expected, **extra):
        # Shape fixtures exercise every required/unknown field in verify.py.
        # Here only generated counters/IDs/times vary: validate their first and
        # last instances, execute EVERY transition and bound EVERY message.
        if action not in validated:
            validators["query" if action == "ready" else action].validate(message)
            validated.add(action)
        assert len(json.dumps(message).encode("utf-8")) <= 4096
        actual = oracle.apply({"action": action, "tick": tick, **extra}, message)
        assert actual == expected, (action, tick, actual, expected)
        assert len(oracle.receipts) <= spec["cache_capacity"]
        assert len(oracle.readiness_cache) <= spec["cache_capacity"]

    oracle = oracle_type(messages["query"], spec["cache_capacity"])
    apply(oracle, "ready", 100000, messages["query"], "ready")
    apply(
        oracle, "result", 100000, messages["result"], "result_accepted", server_tick=100
    )
    apply(oracle, "start", 100100, messages["start"], "started")
    initial_i = messages["start"]["issued_at_ms"]
    first_renew = None
    for index in range(1, spec["renewals"] + 1):
        command = {
            **messages["renew"],
            "command_id": uuid(index + 100),
            "command_seq": index + 1,
            "issued_at_ms": initial_i + index * 30000,
            "expires_at_ms": initial_i + index * 30000 + 60000,
        }
        if first_renew is None:
            first_renew = copy.deepcopy(command)
        apply(oracle, "renew", 100000 + index * 30000, command, "renewed")
        assert oracle.active["r"] == 100000 and oracle.active["i"] == initial_i
        assert oracle.active["deadline"] == 160000 + index * 30000
    validators["renew"].validate(command)
    tick = oracle.last_tick
    apply(oracle, "renew", tick, first_renew, "stale_command")
    apply(oracle, "start", tick, messages["start"], "stale_command")
    oracle.apply({"action": "invalidate", "tick": tick}, {})
    old_start = old_query = None
    for index in range(2, spec["attempts"] + 2):
        tick += 10000
        patch = {"admission_seq": index, "readiness_nonce": uuid(index + 100000)}
        offset = tick - 100000
        query = {
            **messages["query"],
            **patch,
            "issued_at_ms": messages["query"]["issued_at_ms"] + offset,
            "expires_at_ms": messages["query"]["expires_at_ms"] + offset,
        }
        result = {**messages["result"], **patch}
        start = {
            **messages["start"],
            **patch,
            "command_id": uuid(index + 200000),
            "lease_id": uuid(index + 300000),
            "stream_instance_id": uuid(index + 400000),
            "issued_at_ms": initial_i + offset,
            "expires_at_ms": initial_i + offset + 60000,
        }
        stop = {
            **messages["stop"],
            **patch,
            "command_id": uuid(index + 500000),
            "lease_id": start["lease_id"],
            "stream_instance_id": start["stream_instance_id"],
            "command_seq": 2,
            "issued_at_ms": initial_i + offset + 1000,
            "expires_at_ms": initial_i + offset + 6000,
        }
        apply(oracle, "query", tick, query, "query_pending", server_tick=tick)
        apply(oracle, "ready", tick, query, "ready")
        apply(
            oracle, "result", tick + 1, result, "result_accepted", server_tick=tick + 1
        )
        apply(oracle, "start", tick + 2, start, "started")
        apply(oracle, "stop", tick + 1000, stop, "stopped")
        apply(oracle, "stop", tick + 1001, stop, "replay")
        if old_start is None:
            old_start, old_query = copy.deepcopy(start), copy.deepcopy(query)
    for name, message in (
        ("query", query),
        ("result", result),
        ("start", start),
        ("stop", stop),
    ):
        validators[name].validate(message)
    apply(oracle, "start", tick + 1002, old_start, "stale_admission")
    apply(oracle, "ready", tick + 1003, old_query, "stale_admission")
    next_epoch = uuid(900000)
    oracle.apply(
        {"action": "epoch_lost", "tick": tick + 1004, "issuer_epoch": next_epoch}, {}
    )
    apply(
        oracle,
        "ready",
        tick + 1005,
        {**old_query, "issuer_epoch": next_epoch},
        "stale_admission",
    )
    apply(
        oracle,
        "query",
        tick + 1006,
        {**old_query, "issuer_epoch": next_epoch},
        "stale_server_sequence",
        server_tick=tick + 1006,
    )
    assert oracle.start_count == spec["attempts"] + 1
    return {
        "renewals": spec["renewals"],
        "new_attempts": spec["attempts"],
        "cache_capacity_each": spec["cache_capacity"],
        "retained_command_results": len(oracle.receipts),
        "retained_readiness_results": len(oracle.readiness_cache),
        "admission_high_water": oracle.admission_hwm,
    }
