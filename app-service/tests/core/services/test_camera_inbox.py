from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from core.camera.runtime_inbox import enqueue
from core.camera.runtime_state import initial_state


def hello(boot="boot", water=1):
    return {
        "type": "camera_enrollment_hello",
        "sn": "fixture",
        "boot_id": boot,
        "enrollment_id": str(uuid4()),
        "admission_high_water": water,
        "revision": "fixture",
    }


def test_new_attempts_materialize_one_pending_hello_and_preserve_commands():
    s = initial_state()
    now = datetime.now(UTC)
    first = enqueue(s, "incoming", hello(), now, now + timedelta(seconds=10))
    command = enqueue(s, "stop", {}, now, now + timedelta(seconds=10))
    for _ in range(100):
        last = hello()
        enqueue(s, "incoming", last, now, now + timedelta(seconds=10))
    assert len(s["jobs"]) == 2
    assert s["jobs"][0]["id"] == command
    assert s["jobs"][1]["value"] == last
    assert len(s["results"]) == 64
    assert first not in s["results"]


def test_duplicate_does_not_extend_ttl_or_change_pending_handshake():
    s = initial_state()
    now = datetime.now(UTC)
    value = hello()
    s["pending"] = {"hello": hello()}
    pending = s["pending"].copy()
    job = enqueue(s, "incoming", value, now, now + timedelta(seconds=10))
    assert enqueue(s, "incoming", value, now, now + timedelta(seconds=20)) == job
    assert s["jobs"][0]["until"] == (now + timedelta(seconds=10)).isoformat()
    assert s["pending"] == pending


def test_different_boot_and_high_water_regression_are_not_merged():
    s = initial_state()
    now = datetime.now(UTC)
    enqueue(s, "incoming", hello(water=3), now, now + timedelta(seconds=10))
    enqueue(s, "incoming", hello(boot="other"), now, now + timedelta(seconds=10))
    with pytest.raises(ValueError, match="high_water_regressed"):
        enqueue(s, "incoming", hello(water=2), now, now + timedelta(seconds=10))
    assert len(s["jobs"]) == 2


def test_expired_full_queue_does_not_block_new_command():
    s = initial_state()
    now = datetime.now(UTC)
    for _ in range(64):
        enqueue(s, "ack", {}, now, now + timedelta(seconds=1))
    enqueue(s, "stop", {}, now + timedelta(seconds=2), now + timedelta(seconds=3))
    assert len(s["jobs"]) == 1
    assert len(s["results"]) == 64
    assert all(v == {"error": "camera_job_expired"} for v in s["results"].values())
