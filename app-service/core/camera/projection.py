"""Negotiated HTTP reader for native camera state, independent of MFT inventory."""

import copy
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import select

from core.camera.admission import camera_from_gauge, validate_gauge
from core.camera.contract import REVISION
from core.camera.native_contract import (
    CAPABILITIES,
    CAPABILITIES3,
    CAPABILITIES4,
    MEDIA11,
    MEDIA12,
    MEDIA13,
    MEDIA3,
    validate11,
    validate12,
    validate13,
)
from core.camera.start_policy import start_enabled
from core.config import settings
from core.models.devices import DeviceConnection, DeviceGauge


class CameraCapabilityView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    camera_contract_revision: Literal["siplite-camera/1.0.0"] = REVISION
    negotiated_v2: Literal[False] = False
    video_capabilities: None = None
    camera: dict[str, Any] | None
    main_app_online: bool
    fresh: bool
    producer_adapter: dict[str, Any]


class CameraCapabilityView11(CameraCapabilityView):
    camera_contract_revision: Literal["siplite-camera/1.1.0"] = MEDIA11
    camera_observation: dict[str, Any] | None
    camera_capabilities: dict[str, Any]

    @model_validator(mode="after")
    def validate_native(self):
        validate11("camera_capabilities", self.camera_capabilities)
        if self.camera_observation is not None:
            validate11("camera_observation", self.camera_observation)
            if (
                self.camera is None
                or self.camera_observation["source_id"] != self.camera["camera_id"]
            ):
                raise ValueError("camera_observation_source_mismatch")
        return self


class CameraCapabilityView12(CameraCapabilityView11):
    camera_contract_revision: Literal["siplite-camera/1.2.0"] = MEDIA12
    contract_version: Literal[3] = 3
    media_contract_revision: Literal["l4-media/3.0.0"] = MEDIA3

    @model_validator(mode="after")
    def validate_native(self):
        validate12("camera_capabilities", self.camera_capabilities)
        if self.camera_observation is not None:
            validate12("camera_observation", self.camera_observation)
            if (
                self.camera is None
                or self.camera_observation["source_id"] != self.camera["camera_id"]
            ):
                raise ValueError("camera_observation_source_mismatch")
        return self


class CameraCapabilityView13(CameraCapabilityView12):
    camera_contract_revision: Literal["siplite-camera/1.3.0"] = MEDIA13

    @model_validator(mode="after")
    def validate_native(self):
        validate13("camera_capabilities", self.camera_capabilities)
        if self.camera_observation is not None:
            validate13("camera_observation", self.camera_observation)
            if (
                self.camera is None
                or self.camera_observation["source_id"] != self.camera["camera_id"]
            ):
                raise ValueError("camera_observation_source_mismatch")
        return self


async def camera_capability(
    session,
    device_id: int,
    *,
    authorized_sn: str | None = None,
    native: bool = False,
    media_version: int = 2,
    camera_revision: str | None = None,
) -> (
    CameraCapabilityView
    | CameraCapabilityView11
    | CameraCapabilityView12
    | CameraCapabilityView13
):
    if (
        camera_revision not in (None, MEDIA11, MEDIA12, MEDIA13)
        or camera_revision == MEDIA13
        and (not native or media_version != 3)
    ):
        raise ValueError("unsupported_camera_projection_selection")
    connection = await session.scalar(
        select(DeviceConnection).where(DeviceConnection.device_id == device_id)
    )
    online = bool(
        connection and connection.app_connect is True and not connection.is_blocked
    )
    gauge = await session.scalar(
        select(DeviceGauge).where(
            DeviceGauge.device_id == device_id,
            DeviceGauge.type == "84",
            DeviceGauge.is_deleted.is_(False),
        )
    )
    camera = None
    observation = None
    fresh = False
    if gauge is not None:
        try:
            validate_gauge(gauge.gauges)
            observed = camera_from_gauge(gauge.gauges, "cam:ip000001")
            if observed and observed.get("camera_contract_revision") == REVISION:
                camera = copy.deepcopy(observed)
            matches = [
                item
                for record in gauge.gauges.get("300", [])
                for item in record.get("450", {}).get("media_observations", [])
                if item["source_id"] == "cam:ip000001"
            ]
            if native and len(matches) == 1:
                observation = (
                    validate13
                    if camera_revision == MEDIA13
                    else validate12 if media_version == 3 else validate11
                )("camera_observation", matches[0])
                if camera:
                    camera["actual_track"] = None
            updated = gauge.updated_at
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=UTC)
            fresh = (
                camera is not None
                and (not native or observation is not None)
                and 0
                <= (datetime.now(UTC) - updated).total_seconds()
                <= (30 if media_version == 3 else 60)
            )
        except ValueError, TypeError, AttributeError, KeyError:
            camera = None
            observation = None
    actual_track = (
        observation.get("actual_track")
        if native and observation
        else None if native else camera.get("actual_track") if camera else None
    )
    reason = (
        "camera_main_app_offline"
        if not online
        else (
            "camera_capabilities_stale"
            if not fresh
            else (
                "camera_actual_track_unknown"
                if actual_track is None
                else (
                    "camera_writers_disabled"
                    if not start_enabled(authorized_sn)
                    else None
                )
            )
        )
    )
    if native and reason is None and not settings.camera.monotonic_runtime_enabled:
        reason = "camera_monotonic_runtime_disabled"
    if native and reason is None and not settings.camera.native_auto_enabled:
        reason = "camera_native_auto_disabled"
    view_type = (
        (
            CameraCapabilityView13
            if camera_revision == MEDIA13
            else (
                CameraCapabilityView12 if media_version == 3 else CameraCapabilityView11
            )
        )
        if native
        else CameraCapabilityView
    )
    extra = (
        {
            "camera_observation": observation,
            "camera_capabilities": copy.deepcopy(
                CAPABILITIES4
                if camera_revision == MEDIA13
                else CAPABILITIES3 if media_version == 3 else CAPABILITIES
            ),
        }
        if native
        else {}
    )
    return view_type(
        **extra,
        camera=camera,
        main_app_online=online,
        fresh=fresh,
        producer_adapter={
            "ready": reason is None,
            "reason": reason,
            "source_type": "camera",
            "source_id": "cam:ip000001",
            "control_version": 1,
            "control_mode": "usb-camera",
            "recovery_policy": "stop_on_failure",
        },
    )
