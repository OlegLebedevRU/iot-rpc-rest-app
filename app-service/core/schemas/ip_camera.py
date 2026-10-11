"""Bounded device RPC envelopes; camera capabilities are checked by siplite."""

from __future__ import annotations

import json
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

IP_CAMERA_GET_STATE = 160
IP_CAMERA_SET_CONFIG = 161
IP_CAMERA_SET_DAY_NIGHT = 162
IP_CAMERA_EVENT = 84
IP_CAMERA_STATE_TAG = "450"

# An advertised camera field still needs approval for the siplite media path.
CAMERA_WRITABLE_FIELDS = frozenset(
    {
        "video0.fps",
        "video0.bitrate",
        "video0.gopSize",
        "video0.rcMode",
        "video0.size",
        "isp.mirror",
        "isp.flip",
        "isp.rotate",
        "isp.luminance",
        "isp.contrast",
        "isp.saturation",
        "isp.hue",
        "nightMode.lightMonitor",
    }
)


class CameraReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    camera_id: str = Field(default="cam:ip000001", pattern=r"^cam:ip[0-9]{6}$")
    timeout_ms: int = Field(default=5000, ge=1000, le=15000)


class CameraWriteRequest(CameraReadRequest):
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    patch: dict[str, dict[str, Any]]
    allow_disruptive: bool = False
    dry_run: bool = False

    @model_validator(mode="after")
    def validate_patch(self):
        count = 0
        for section, fields in self.patch.items():
            if not fields:
                raise ValueError("patch sections must not be empty")
            for field, value in fields.items():
                path = f"{section}.{field}"
                if path not in CAMERA_WRITABLE_FIELDS:
                    raise ValueError(f"camera field is not permitted: {path}")
                if path == "nightMode.lightMonitor" and type(value) is not bool:
                    raise ValueError("lightMonitor must be a boolean")
                if type(value) not in (bool, int, float, str):
                    raise ValueError(f"camera value must be a scalar: {path}")
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError(f"camera value must be finite: {path}")
                if isinstance(value, str) and len(value) > 64:
                    raise ValueError(f"camera string is too long: {path}")
                count += 1
        if count == 0 or count > 12:
            raise ValueError("patch must contain 1..12 fields")
        return self


class CameraReadPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dt: list[CameraReadRequest] = Field(min_length=1, max_length=1)


class CameraWritePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dt: list[CameraWriteRequest] = Field(min_length=1, max_length=1)


class CameraDayNightRequest(CameraReadRequest):
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    mode: Literal["auto", "day", "night"]
    allow_disruptive: bool = False
    dry_run: bool = False


class CameraDayNightPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dt: list[CameraDayNightRequest] = Field(min_length=1, max_length=1)


def validate_ip_camera_payload(method_code: int, payload: Any) -> dict[str, Any]:
    # Count incoming bytes before normalization, including escaped/non-ASCII data.
    try:
        size = len(json.dumps(payload, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ValueError("camera payload must be finite JSON") from exc
    if size > 4096:
        raise ValueError("camera payload exceeds 4096 bytes")
    models = {
        IP_CAMERA_GET_STATE: CameraReadPayload,
        IP_CAMERA_SET_CONFIG: CameraWritePayload,
        IP_CAMERA_SET_DAY_NIGHT: CameraDayNightPayload,
    }
    if method_code not in models:
        raise ValueError("unknown camera RPC method")
    return models[method_code].model_validate(payload).model_dump(mode="json")
