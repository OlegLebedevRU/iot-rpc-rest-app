"""Negotiated HTTP reader for native camera state, independent of MFT inventory."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from core.camera.admission import camera_from_gauge, validate_gauge
from core.camera.contract import REVISION
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


async def camera_capability(session, device_id: int) -> CameraCapabilityView:
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
    fresh = False
    if gauge is not None:
        try:
            validate_gauge(gauge.gauges)
            observed = camera_from_gauge(gauge.gauges, "cam:ip000001")
            if observed and observed.get("camera_contract_revision") == REVISION:
                camera = observed
            updated = gauge.updated_at
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=UTC)
            fresh = (
                camera is not None
                and 0 <= (datetime.now(UTC) - updated).total_seconds() <= 60
            )
        except ValueError, TypeError, AttributeError, KeyError:
            camera = None
    reason = (
        "camera_main_app_offline"
        if not online
        else (
            "camera_capabilities_stale"
            if not fresh
            else (
                "camera_actual_track_unknown"
                if camera.get("actual_track") is None
                else (
                    "camera_writers_disabled"
                    if not settings.camera.writers_enabled
                    else None
                )
            )
        )
    )
    return CameraCapabilityView(
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
