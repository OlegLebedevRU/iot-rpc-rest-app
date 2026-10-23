"""Adapt the inspected siplite CTL v1 camera producer without desktop probes."""

from uuid import UUID, uuid4
from typing import Literal

from core.camera.contract import REVISION
from core.camera.media import CameraEpoch
from core.config import settings
from core.remote_input.schemas import StreamStartCommand, StreamStopCommand


class CameraRenewCommand(StreamStopCommand):
    type: Literal["lease_renew"] = "lease_renew"
    ttl_sec: int = 60


def start_command(epoch: CameraEpoch, camera: dict, now_ms: int) -> StreamStartCommand:
    if not settings.camera.writers_enabled:
        raise ValueError("camera_writers_disabled")
    start = epoch.start
    descriptor = start["descriptor"]
    if (
        camera.get("camera_contract_revision") != REVISION
        or descriptor["source_id"] != camera.get("camera_id")
        or descriptor["tracks"][0] != camera.get("actual_track")
    ):
        raise ValueError("camera_actual_descriptor_mismatch")
    deadline = start["lease_expires_at"] * 1000
    if deadline <= now_ms:
        raise ValueError("camera_lease_expired")
    # l4_video_ctl.c inventory() / dispatch() uses this exact v1 identity.
    # The media side keeps source_type=camera and the honest immutable descriptor.
    return StreamStartCommand(
        command_id=UUID(start["operation_id"]),
        lease_id=UUID(start["lease_id"]),
        sn=start["publisher"]["sn"],
        mode="usb-camera",
        source_id=camera["camera_id"],
        profile="default",
        stream_instance_id=UUID(start["publisher"]["stream_instance_id"]),
        issued_at_ms=now_ms,
        expires_at_ms=deadline,
    )


def stop_command(epoch: CameraEpoch, now_ms: int) -> StreamStopCommand:
    identity = epoch.identity
    return StreamStopCommand(
        command_id=uuid4(),
        lease_id=UUID(identity["lease_id"]),
        sn=identity["sn"],
        stream_instance_id=UUID(identity["stream_instance_id"]),
        issued_at_ms=now_ms,
        expires_at_ms=now_ms + 5000,
    )


def renew_command(epoch: CameraEpoch, lease, now_ms: int) -> CameraRenewCommand:
    identity = epoch.identity
    if (
        not lease.is_active()
        or lease.scope != "stream"
        or lease.sn != identity["sn"]
        or str(lease.lease_id) != identity["lease_id"]
    ):
        raise ValueError("camera_lease_mismatch")
    return CameraRenewCommand(
        command_id=uuid4(),
        lease_id=lease.lease_id,
        sn=lease.sn,
        stream_instance_id=UUID(identity["stream_instance_id"]),
        issued_at_ms=now_ms,
        expires_at_ms=int(lease.expires_at.timestamp() * 1000),
    )
