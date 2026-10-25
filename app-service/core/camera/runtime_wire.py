"""Strict negotiated camera wire messages; frozen desktop envelopes stay intact."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from jsonschema import FormatChecker
from pydantic import RootModel
from referencing import Registry, Resource

from core.camera.contract import StrictValidator, bounded_json
from core.camera.native_contract import ENROLLMENT02, ENROLLMENT03, schema11, schema3
from core.remote_input.video_wire import load_object

ENROLLMENT = "camera-enrollment/0.1.0-proposed"
ADMISSION = "camera-ctl-monotonic/0.2.0-proposed"
MAX_COUNTER = (1 << 53) - 1
ROOT = Path(__file__).resolve().parents[3] / "contracts"


@lru_cache
def validator(enrollment: bool | str) -> StrictValidator:
    if enrollment in (ENROLLMENT02, ENROLLMENT03):
        schema = json.loads(
            (
                ROOT
                / (
                    "camera-enrollment-v0.3/schema.json"
                    if enrollment == ENROLLMENT03
                    else "camera-enrollment-v0.2/schema.json"
                )
            ).read_text(encoding="utf-8")
        )
        admission = json.loads(
            (ROOT / "camera-ctl-monotonic-v1/camera-ctl.schema.json").read_text(
                encoding="utf-8"
            )
        )
        registry = Registry().with_resources(
            [
                ("urn:leo4:siplite-camera:1.1.0", Resource.from_contents(schema11())),
                ("urn:leo4:l4-media:3.0.0", Resource.from_contents(schema3())),
                ("urn:leo4:camera-admission:0.2.0", Resource.from_contents(admission)),
            ]
        )
        return StrictValidator(
            schema, registry=registry, format_checker=FormatChecker()
        )
    path = ROOT / (
        "camera-enrollment-proposal/schema.json"
        if enrollment
        else "camera-ctl-monotonic-v1/camera-ctl.schema.json"
    )
    return StrictValidator(
        json.loads(path.read_text(encoding="utf-8")), format_checker=FormatChecker()
    )


def validate(message: dict) -> dict:
    bounded_json(message, 4096, 8)
    revision = message.get("revision")
    selector = (
        revision if revision in (ENROLLMENT02, ENROLLMENT03) else revision == ENROLLMENT
    )
    if not validator(selector).is_valid(message):
        raise ValueError("invalid_camera_runtime_message")
    if revision in (ENROLLMENT, ENROLLMENT02, ENROLLMENT03) and any(
        UUID(message[k]).version != 4 or str(UUID(message[k])) != message[k]
        for k in ("boot_id", "enrollment_id")
    ):
        raise ValueError("camera_enrollment_uuid_canonical_v4_required")
    if (
        revision in (ENROLLMENT02, ENROLLMENT03)
        and message["type"] != "camera_enrollment_hello"
    ):
        binding, descriptor = message["binding"], message["descriptor"]
        if revision == ENROLLMENT03 and descriptor["source_type"] != "camera":
            raise ValueError("camera_source_type_required")
        if (
            binding["boot_id"] != message["boot_id"]
            or binding["source_id"] != descriptor["source_id"]
            or binding["codec"] != descriptor["tracks"][0]["codec"]
            or binding["descriptor_sha256"] != digest(descriptor)
            or message["binding_hash"] != digest(binding)
            or not binding["path_generation"].endswith(
                "/" + str(descriptor["geometry_generation"])
            )
        ):
            raise ValueError("camera_enrollment_complete_binding_mismatch")
    return message


def decode(payload: bytes | str | dict, sn: str, correlation: str | None) -> dict:
    message = validate(load_object(payload, 4096))
    expected = message.get("enrollment_id", message.get("readiness_nonce"))
    if message["sn"] != sn or correlation != expected:
        raise ValueError("camera_runtime_correlation")
    if "enrollment_id" in message and any(
        UUID(message[k]).version != 4 for k in ("boot_id", "enrollment_id")
    ):
        raise ValueError("camera_enrollment_uuid_version")
    if message["type"] not in (
        "camera_enrollment_hello",
        "camera_enrollment_proof",
        "camera_readiness_result",
    ):
        raise ValueError("camera_runtime_direction")
    return message


def canonical(value: Any) -> str:
    """JCS for the negotiated integer-only descriptor/binding domain."""
    if value is None or type(value) is bool:
        return json.dumps(value)
    if type(value) is int and -MAX_COUNTER <= value <= MAX_COUNTER:
        return str(value)
    if isinstance(value, str):
        value.encode("utf-8")
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(canonical(v) for v in value) + "]"
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return (
            "{"
            + ",".join(
                canonical(k) + ":" + canonical(value[k])
                for k in sorted(value, key=lambda k: k.encode("utf-16-be"))
            )
            + "}"
        )
    raise ValueError("camera_descriptor_numeric_domain")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


class CameraRuntimeCommand(RootModel[dict[str, Any]]):
    @property
    def command_id(self) -> UUID:
        return UUID(self.root["command_id"])

    @property
    def lease_id(self) -> UUID:
        return UUID(self.root["lease_id"])

    @property
    def stream_instance_id(self) -> UUID:
        return UUID(self.root["stream_instance_id"])

    @property
    def source_id(self) -> str:
        return self.root["binding"]["source_id"]

    @property
    def type(self) -> str:
        return self.root["type"]

    @property
    def expires_at_ms(self) -> int:
        return self.root["expires_at_ms"]

    @property
    def ttl_sec(self) -> int:
        return 60
