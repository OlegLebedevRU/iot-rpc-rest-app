"""Camera authority comes from main_app gauge84, never desktop CTL presence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from core.camera.contract import REVISION, bounded_json, validate_definition
from core.camera.native_contract import validate11, validate12, MEDIA12
from core.config import settings
from core.models.devices import DeviceConnection, DeviceGauge
from core.rpc_redaction import redact_rpc


def camera_from_gauge(payload: dict, camera_id: str) -> dict | None:
    for record in payload.get("300", []):
        state = record.get("450", {})
        for camera in state.get("cameras", []):
            if camera.get("camera_id") == camera_id:
                return camera
    return None


def validate_gauge(payload: Any) -> dict:
    bounded_json(payload, 32768)
    if redact_rpc(payload) != payload:
        raise ValueError("camera_snapshot_contains_credentials")
    seen = set()
    for record in payload.get("300", []):
        state = record.get("450", {})
        observations = state.get("media_observations", [])
        if not isinstance(observations, list) or len(observations) > 16:
            raise ValueError("camera_observation_bounds")
        for observation in observations:
            (
                validate12
                if observation.get("camera_contract_revision") == MEDIA12
                else validate11
            )("camera_observation", observation)
            if observation["source_id"] in seen:
                raise ValueError("camera_observation_duplicate")
            seen.add(observation["source_id"])
        for camera in state.get("cameras", []):
            revision = camera.get("camera_contract_revision")
            if revision is None:
                continue  # Existing schema_version=1 snapshots remain readable.
            if "hardware_id" in camera:
                raise ValueError("camera_local_wrapper_not_allowed")
            if revision != REVISION:
                raise ValueError("unsupported_camera_contract")
            # The cloud wrapper retains its existing root and camera fields.
            # Validate each advertised extension using the exact local definition.
            local = {
                "v": 1,
                "hardware_id": "cloud-wrapper",
                "contract_revision": revision,
                "snapshot_id": state.get("snapshot_id"),
                **{
                    key: camera.get(key)
                    for key in (
                        "camera_id",
                        "revision",
                        "discovery",
                        "auth_source",
                        "has_credentials",
                        "actual_track",
                        "config",
                        "capabilities",
                        "operation",
                    )
                },
            }
            validate_definition("local-camera.schema.json", "camera_snapshot", local)
    return payload


def require_camera_operation(method: int, item: dict, camera: dict) -> None:
    if camera.get("camera_contract_revision") != REVISION:
        raise HTTPException(409, "camera_contract_not_negotiated")
    caps = camera.get("capabilities", {})
    if method not in caps.get("methods", []):
        raise HTTPException(409, "camera_method_unsupported")
    if method != 160 and not settings.camera.writers_enabled:
        raise HTTPException(409, "camera_writers_disabled")
    if "expected_revision" in item and item["expected_revision"] != camera.get(
        "revision"
    ):
        raise HTTPException(409, "camera_revision_conflict")
    if method == 161:
        fields = {entry["path"]: entry for entry in caps.get("fields", [])}
        for section, values in item["patch"].items():
            for key, value in values.items():
                field = fields.get(f"{section}.{key}")
                if field is None or field.get("write") is not True:
                    raise HTTPException(409, "camera_field_not_writable")
                if field.get("disruptive") and not item["allow_disruptive"]:
                    raise HTTPException(409, "camera_disruptive_confirmation_required")
                if field.get("values") and value not in field["values"]:
                    raise HTTPException(409, "camera_value_unsupported")
                if type(value) in (int, float):
                    low, high = field.get("minimum"), field.get("maximum")
                    if (low is not None and value < low) or (
                        high is not None and value > high
                    ):
                        raise HTTPException(409, "camera_value_out_of_range")
    if method == 166:
        if item["action"] == "bind":
            discovery = camera.get("discovery", {})
            if (
                discovery.get("physical_port") != 2
                or discovery.get("generation") != item["discovery_generation"]
            ):
                raise HTTPException(409, "camera_discovery_conflict")
            if not any(
                c.get("mac") == item["candidate_mac"] and c.get("port_verified") is True
                for c in discovery.get("candidates", [])
            ):
                raise HTTPException(409, "camera_candidate_not_found")
    if method == 167 and item["action"] != "cancel":
        # TASK-10 stock-only imported profile has no verified native recovery contract.
        # Host simulations and model results cannot open this hardware gate.
        raise HTTPException(409, "camera_physical_illumination_unverified")


async def admit_task(session, task, sn: str) -> None:
    if task.camera_contract_revision is None:
        return
    item = task.payload["dt"][0]
    connection = await session.scalar(
        select(DeviceConnection).where(DeviceConnection.device_id == task.device_id)
    )
    if (
        connection is None
        or connection.app_connect is not True
        or connection.is_blocked
    ):
        raise HTTPException(409, "camera_main_app_offline")
    gauge = await session.scalar(
        select(DeviceGauge).where(
            DeviceGauge.device_id == task.device_id,
            DeviceGauge.type == "84",
            DeviceGauge.is_deleted.is_(False),
        )
    )
    now = datetime.now(UTC)
    updated = None if gauge is None else gauge.updated_at
    if updated is not None and updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    if updated is None or not 0 <= (now - updated).total_seconds() <= 60:
        raise HTTPException(409, "camera_capabilities_stale")
    try:
        validate_gauge(gauge.gauges)
        camera = camera_from_gauge(gauge.gauges, item["camera_id"])
    except ValueError, TypeError, KeyError, AttributeError:
        raise HTTPException(409, "camera_capabilities_invalid") from None
    if camera is None:
        raise HTTPException(409, "camera_not_found")
    envelope = item.get("sealed_credentials")
    if envelope is not None:
        now_ms = int(now.timestamp() * 1000)
        if (
            envelope["sn"] != sn
            or not now_ms < envelope["expires_at_ms"] <= now_ms + 60000
            or envelope["expires_at_ms"] > now_ms + task.ttl * 60000
        ):
            raise HTTPException(409, "credential_binding_or_deadline")
    require_camera_operation(task.method_code, item, camera)
    if task.method_code in (161, 162, 163, 164, 166, 167) and not item.get(
        "dry_run", False
    ):
        from core.remote_input.leases import lease_registry

        active = await lease_registry.get_active_by_sn(sn)
        if (
            active
            and active.stream_instance_id is not None
            and item.get("action") != "cancel"
        ):
            raise HTTPException(409, "camera_busy_stream")
