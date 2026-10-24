"""Independent full-offer/physical-facts and original-budget reference checks."""

import argparse
import copy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parent


def read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def canonical(value):
    # The complete fixtures are ASCII-key integer-domain descriptors/bindings.
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


schema = read("schema.json")
registry = Registry().with_resources(
    [
        (
            "urn:leo4:siplite-camera:1.1.0",
            Resource.from_contents(read("../siplite-camera-v1.1/hevc.schema.json")),
        ),
        (
            "urn:leo4:camera-admission:0.2.0",
            Resource.from_contents(
                read("../camera-ctl-monotonic-v1/camera-ctl.schema.json")
            ),
        ),
    ]
)
validator = Draft202012Validator(
    schema, registry=registry, format_checker=FormatChecker()
)


def physical_offer(offer, hello, observation, camera):
    """Descriptor revision comes from the authenticated offer, not a local guess."""
    if not validator.is_valid(offer):
        return False
    d, b = offer["descriptor"], offer["binding"]
    expected = {
        "boot_id": hello["boot_id"],
        "source_id": camera["camera_id"],
        "physical_camera_mac": camera["discovery"]["candidates"][0]["mac"],
        "path_generation": f"port2/{camera['discovery']['generation']}/{observation['geometry_generation']}",
        "codec": observation["actual_track"]["codec"],
        "descriptor_sha256": sha(d),
    }
    return (
        all(
            offer[k] == hello[k] for k in ("revision", "sn", "boot_id", "enrollment_id")
        )
        and d["source_id"] == observation["source_id"] == camera["camera_id"]
        and d["geometry_generation"] == observation["geometry_generation"]
        and d["tracks"] == [observation["actual_track"]]
        and d["camera_contract_revision"] == observation["camera_contract_revision"]
        and d["cadence_revision"] == observation["cadence_revision"]
        and camera["discovery"]["physical_port"] == 2
        and camera["discovery"]["candidates"][0]["port_verified"] is True
        and camera["discovery"]["candidates"][0]["auth"] == "verified"
        and b == expected
        and offer["binding_hash"] == sha(b)
    )


class Device:
    def __init__(self, hello, observation, camera):
        self.hello, self.observation, self.camera = hello, observation, camera
        self.high_water = hello["admission_high_water"]
        self.pending = None
        self.deadline = 5000

    def offer(self, message, tick):
        if tick >= self.deadline or not physical_offer(
            message, self.hello, self.observation, self.camera
        ):
            return False
        if self.pending is not None and self.pending != message:
            return False
        self.pending = copy.deepcopy(message)
        return True

    def commit(self, message, tick):
        if (
            tick >= self.deadline
            or self.pending is None
            or not validator.is_valid(message)
        ):
            return False
        if any(
            message[k] != v
            for k, v in self.pending.items()
            if k not in ("type", "admission_floor")
        ):
            return False
        if message["admission_high_water"] != self.high_water or message[
            "admission_floor"
        ] < max(self.high_water, self.pending["admission_floor"]):
            return False
        self.high_water = message["admission_floor"]
        self.pending = None
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict-bytes",
        action="store_true",
        help="Hash raw exported Git bytes without checkout newline normalization",
    )
    args = parser.parse_args()

    def file_sha(path):
        raw = path.read_bytes()
        # Pins identify LF Git text blobs, never a developer's CRLF checkout.
        if not args.strict_bytes:
            raw = raw.replace(b"\r\n", b"\n")
        return hashlib.sha256(raw).hexdigest()

    manifest = read("manifest.json")
    for name, expected in manifest["fixtures"].items():
        assert file_sha(ROOT / "fixtures" / name) == expected, name
    for path, expected in (
        (ROOT / "schema.json", manifest["schema_sha256"]),
        (
            ROOT.parent / "siplite-camera-v1.1/hevc.schema.json",
            manifest["media_schema_sha256"],
        ),
        (
            ROOT.parent / "camera-ctl-monotonic-v1/camera-ctl.schema.json",
            manifest["admission_schema_sha256"],
        ),
    ):
        assert file_sha(path) == expected, path
    hello, offer, proof, commit = [
        read("fixtures/" + name + ".json")
        for name in ("hello", "offer", "proof", "commit")
    ]
    for message in (hello, offer, proof, commit):
        validator.validate(message)
        assert len(canonical(message).encode()) <= 4096
    observation, camera = read("fixtures/observation.json"), read(
        "fixtures/physical-camera.json"
    )
    device = Device(hello, observation, camera)
    assert device.offer(offer, 10)
    before = copy.deepcopy(vars(device))
    assert not device.commit({**commit, "admission_floor": 42}, 20)
    assert vars(device) == before
    assert device.offer(offer, 4998)
    assert device.commit(commit, 4999) and device.high_water == 100
    for tick in (5000, 5001):
        device = Device(hello, observation, camera)
        assert device.offer(offer, 10)
        assert not device.commit(commit, tick) and device.high_water == 41
    mutations = 0
    for field, replacement in (
        ("boot_id", hello["enrollment_id"]),
        ("physical_camera_mac", "02:00:00:00:00:02"),
        ("path_generation", "port2/4/17"),
        ("codec", "h264"),
        ("descriptor_sha256", "a" * 64),
    ):
        changed = copy.deepcopy(offer)
        changed["binding"][field] = replacement
        changed["binding_hash"] = sha(changed["binding"])
        assert not physical_offer(changed, hello, observation, camera)
        mutations += 1
    for field, replacement in (
        ("geometry_generation", 18),
        ("cadence_revision", "constant-policy"),
    ):
        changed = copy.deepcopy(offer)
        changed["descriptor"][field] = replacement
        changed["binding"]["descriptor_sha256"] = sha(changed["descriptor"])
        changed["binding_hash"] = sha(changed["binding"])
        assert not physical_offer(changed, hello, observation, camera)
        mutations += 1
    print(
        json.dumps(
            {
                "wire_fixtures": 4,
                "physical_binding_mutations_rejected": mutations,
                "complete_offer_utf8_bytes": len(canonical(offer).encode()),
                "floor100_commit42_rejected": True,
                "original_deadline": True,
                "runtime_authority": False,
            }
        )
    )


if __name__ == "__main__":
    main()
