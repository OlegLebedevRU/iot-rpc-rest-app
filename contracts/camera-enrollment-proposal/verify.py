"""Stateful enrollment transcript oracle; no runtime authentication implementation."""

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA = json.loads(Path(__file__).with_name("schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
BASE = {
    "revision": "camera-enrollment/0.1.0-proposed",
    "sn": "fixture-terminal",
    "boot_id": "00000000-0000-4000-8000-000000000001",
    "enrollment_id": "00000000-0000-4000-8000-000000000002",
}
OFFER = dict(
    BASE,
    type="camera_enrollment_offer",
    ctl_revision="camera-ctl-monotonic/0.2.0-proposed",
    server_challenge="00000000-0000-4000-8000-000000000003",
    issuer_generation=2,
    issuer_epoch="00000000-0000-4000-8000-000000000004",
    binding_hash="a" * 64,
    admission_floor=41,
)


class Device:
    def __init__(self):
        self.high_water = 41
        self.generation = 1
        self.epoch = "00000000-0000-4000-8000-000000000005"
        self.pending = None
        self.complete = False

    def accept(
        self, message, tick, authenticated=True, transport_sn="fixture-terminal"
    ):
        if (
            not VALIDATOR.is_valid(message)
            or not authenticated
            or message["sn"] != transport_sn
        ):
            return False
        if tick >= 5000 or any(
            message[k] != BASE[k] for k in ("boot_id", "enrollment_id")
        ):
            return False
        if (
            message["issuer_generation"] < self.generation
            or (
                message["issuer_generation"] == self.generation
                and message["issuer_epoch"] != self.epoch
            )
            or message["binding_hash"] != "a" * 64
            or message["admission_floor"] < self.high_water
        ):
            return False
        if message["type"] == "camera_enrollment_offer":
            if self.complete:
                return False
            if self.pending is not None and self.pending != message:
                return False
            self.pending = copy.deepcopy(message)
            return True
        if message["type"] != "camera_enrollment_commit" or self.pending is None:
            return False
        if any(
            message[k] != v
            for k, v in self.pending.items()
            if k not in ("type", "admission_floor")
        ):
            return False
        if message["admission_high_water"] != self.high_water:
            return False
        if message["admission_floor"] < self.pending["admission_floor"]:
            return False
        self.high_water = message["admission_floor"]
        self.generation, self.epoch = (
            message["issuer_generation"],
            message["issuer_epoch"],
        )
        self.pending = None
        self.complete = True
        return True


class Server:
    """One durable owner, modeled CAS; transport authentication is an input."""

    def __init__(self):
        self.generation = 2
        self.retired = {"00000000-0000-4000-8000-000000000099"}
        self.boot = "00000000-0000-4000-8000-000000000098"
        self.floor = 41
        self.pending = None

    def hello(self, message, authenticated=True):
        if (
            not authenticated
            or not VALIDATOR.is_valid(message)
            or message["boot_id"] in self.retired
        ):
            return False
        self.pending = dict(
            OFFER, boot_id=message["boot_id"], enrollment_id=message["enrollment_id"]
        )
        return True

    def proof(self, message, tick, owner_generation):
        if (
            not self.pending
            or tick >= 5000
            or owner_generation != self.generation
            or not VALIDATOR.is_valid(message)
            or message["boot_id"] in self.retired
            or any(message[k] != v for k, v in self.pending.items() if k != "type")
        ):
            return False
        self.floor = max(
            self.floor, message["admission_high_water"], message["admission_floor"]
        )
        if self.boot != message["boot_id"]:
            self.retired.add(self.boot)
        self.boot = message["boot_id"]
        self.pending = None
        return True


def verify_commit_floors():
    """Commit cannot weaken an accepted offer or refresh its original budget."""
    vectors = json.loads(
        Path(__file__).with_name("commit-floor-vectors.json").read_text()
    )
    checks = 0
    for case in vectors["cases"]:
        device = Device()
        device.high_water = case["initial_high_water"]
        offer = dict(OFFER, admission_floor=case["offered_floor"])
        assert device.accept(offer, 10), case["name"]
        # Exercise a current high-water that advanced since the offer/proof.
        device.high_water = case["current_high_water"]
        commit = dict(
            offer,
            type="camera_enrollment_commit",
            admission_floor=case["commit_floor"],
            admission_high_water=case["proof_high_water"],
        )
        VALIDATOR.validate(commit)
        before = copy.deepcopy(vars(device))
        assert device.accept(commit, 20) == case["accepted"], case["name"]
        if case["accepted"]:
            assert device.high_water == case["commit_floor"], case["name"]
            assert device.pending is None and device.complete, case["name"]
        else:
            assert vars(device) == before, case["name"]
            assert not device.accept(commit, 21), case["name"]
            assert vars(device) == before, case["name"]
            corrected = dict(
                commit,
                admission_floor=max(case["offered_floor"], case["current_high_water"]),
                admission_high_water=case["current_high_water"],
            )
            # Reuse the same challenge, pending offer and original budget.
            assert device.accept(corrected, 4999), case["name"]
        complete = copy.deepcopy(vars(device))
        assert not device.accept(offer, 4999), case["name"]
        assert not device.accept(commit, 4999), case["name"]
        assert vars(device) == complete, case["name"]
        checks += 1

    for case in vectors["deadline_cases"]:
        device = Device()
        offer = dict(OFFER, admission_floor=100)
        assert device.accept(offer, 10)
        bad = dict(
            offer,
            type="camera_enrollment_commit",
            admission_floor=42,
            admission_high_water=41,
        )
        before = copy.deepcopy(vars(device))
        assert not device.accept(bad, 20)
        assert vars(device) == before
        assert device.accept(offer, 4998)  # duplicate offer does not restart the budget
        assert not device.accept(bad, 4999)
        assert vars(device) == before
        corrected = dict(bad, admission_floor=100)
        assert device.accept(corrected, case["tick"]) == case["accepted"], case["name"]
        if not case["accepted"]:
            assert vars(device) == before, case["name"]
        checks += 1
    return checks


def main():
    hello = dict(
        BASE,
        type="camera_enrollment_hello",
        admission_high_water=41,
        supported_ctl=["camera-ctl-monotonic/0.2.0-proposed"],
    )
    proof = dict(OFFER, type="camera_enrollment_proof", admission_high_water=41)
    commit = dict(proof, type="camera_enrollment_commit", admission_floor=42)
    for message in (hello, OFFER, proof, commit):
        VALIDATOR.validate(message)
    device = Device()
    assert device.accept(OFFER, 10) and device.accept(OFFER, 20)
    assert device.accept(commit, 30) and device.high_water == 42
    assert not device.accept(OFFER, 40)  # cannot restore consumed enrollment
    checks = 3
    for field, value in [
        ("boot_id", "00000000-0000-4000-8000-000000000099"),
        ("enrollment_id", "00000000-0000-4000-8000-000000000099"),
        ("issuer_generation", 0),
        ("binding_hash", "b" * 64),
        ("admission_floor", 40),
        ("revision", "unknown"),
    ]:
        assert not Device().accept(dict(OFFER, **{field: value}), 10)
        checks += 1
    assert not Device().accept(OFFER, 5000)
    assert not Device().accept(OFFER, 10, authenticated=False)
    assert not Device().accept(OFFER, 10, transport_sn="other")
    assert not Device().accept(commit, 10)  # restarted/lost pending
    device = Device()
    assert device.accept(OFFER, 10)
    assert not device.accept(commit, 5000)
    assert not device.accept(dict(commit, server_challenge=BASE["boot_id"]), 20)
    assert not VALIDATOR.is_valid(dict(OFFER, unexpected=True))
    server = Server()
    assert not server.hello(dict(hello, boot_id="00000000-0000-4000-8000-000000000099"))
    assert server.hello(hello) and server.boot != hello["boot_id"]
    assert not server.proof(proof, 100, 1)
    assert not server.proof(proof, 5000, 2)
    assert server.proof(proof, 100, 2) and server.boot == hello["boot_id"]
    assert not server.proof(proof, 200, 2)
    assert server.floor == 41
    floor_checks = verify_commit_floors()
    print(
        json.dumps(
            {
                "checks": checks + 14,
                "commit_floor_cases": floor_checks,
                "runtime_handlers": False,
            }
        )
    )


if __name__ == "__main__":
    main()
