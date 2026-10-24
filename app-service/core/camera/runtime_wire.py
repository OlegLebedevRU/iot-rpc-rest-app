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

from core.camera.contract import StrictValidator, bounded_json
from core.remote_input.video_wire import load_object

ENROLLMENT = "camera-enrollment/0.1.0-proposed"
ADMISSION = "camera-ctl-monotonic/0.2.0-proposed"
MAX_COUNTER = (1 << 53) - 1
ROOT = Path(__file__).resolve().parents[3] / "contracts"


@lru_cache
def validator(enrollment: bool) -> StrictValidator:
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
    if not validator(message.get("revision") == ENROLLMENT).is_valid(message):
        raise ValueError("invalid_camera_runtime_message")
    if message.get("revision") == ENROLLMENT and any(
        UUID(message[k]).version != 4 or str(UUID(message[k])) != message[k]
        for k in ("boot_id", "enrollment_id")
    ):
        raise ValueError("camera_enrollment_uuid_canonical_v4_required")
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
