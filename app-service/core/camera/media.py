"""Negotiated camera media lifecycle; producer START is a separate firmware gate."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import httpx

from core.camera.contract import REVISION
from core.camera.native_contract import (
    CAPABILITIES,
    MEDIA11,
    MEDIA12,
    MEDIA13,
    MEDIA14,
    MEDIA3,
    SELECTED,
    SELECTED3,
    SELECTED4,
    SELECTED5,
    headers11,
    validate_media,
)


@dataclass(frozen=True)
class CodecEvidence:
    checked_at_ms: int
    valid_until_ms: int
    h264: str
    h265: str


def resolve_codec(
    policy: str, evidence: dict[str, CodecEvidence], now_ms: int
) -> tuple[str, str]:
    if policy not in ("auto", "h264", "h265") or set(evidence) != {
        "camera",
        "relay",
        "server",
        "browser",
    }:
        raise ValueError("camera_capability_chain_incomplete")
    for entry in evidence.values():
        if (
            not entry.checked_at_ms <= now_ms < entry.valid_until_ms
            or entry.valid_until_ms - entry.checked_at_ms > 60000
        ):
            raise ValueError("camera_capability_chain_unknown_or_stale")
    if policy in ("auto", "h265") and all(e.h265 == "ready" for e in evidence.values()):
        return "h265", "camera_chain_h265_ready"
    if policy == "h265":
        raise ValueError("camera_h265_unsupported")
    if policy == "auto" and any(
        e.h265 not in ("ready", "unsupported") for e in evidence.values()
    ):
        raise ValueError("camera_capability_chain_unknown_or_stale")
    if all(e.h264 == "ready" for e in evidence.values()):
        return "h264", (
            "explicit_h264" if policy == "h264" else "camera_chain_h265_unsupported"
        )
    raise ValueError("camera_h264_unsupported")


def require_server_format(capabilities: dict, descriptor: dict) -> None:
    track = descriptor["tracks"][0]
    if descriptor.get("contract_version") == 3:
        if (
            not capabilities.get("dependencies_ready")
            or track["codec"] not in capabilities.get("codecs", [])
            or (
                track["codec"] == "h265"
                and capabilities.get("hevc_runtime_verified") is not True
            )
        ):
            raise ValueError("camera_server_format_unavailable")
        if any(
            all(
                track[key] == fmt[key]
                for key in ("codec", "codec_profile", "packetization", "clock_rate")
            )
            for fmt in capabilities.get("formats", [])
        ):
            return
        raise ValueError("camera_server_format_unavailable")
    for fmt in capabilities.get(
        "formats" if descriptor.get("contract_version") == 3 else "camera_formats", []
    ):
        if (
            fmt["runtime_verified"] is True
            and fmt["codec"] == track["codec"]
            and track["codec_profile"] in fmt["codec_profiles"]
            and track["width"] <= fmt["max_width"]
            and track["height"] <= fmt["max_height"]
            and track["fps"] <= fmt["max_fps"]
            and all(
                track[key] == fmt[key]
                for key in ("bit_depth", "chroma", "max_b_frames", "packetization")
            )
            and (track["codec"] != "h265" or track["level_id"] in fmt["level_ids"])
            and (
                track["width"] <= 1920
                and track["height"] <= 1080
                or track["fps"] <= fmt["max_fps_above_full_hd"]
            )
        ):
            return
    raise ValueError("camera_server_format_unavailable")


@dataclass(frozen=True)
class CameraEpoch:
    # Canonical immutable JSON prevents later caller mutation of the descriptor.
    start_json: str
    route_generation: int | None = None
    media_clock_id: str | None = None

    @classmethod
    def from_start(
        cls, payload: dict, lease, now_ms: int | None = None, *, media_lease=None
    ):
        value = validate_media("media_start", payload)
        descriptor = value["descriptor"]
        if (
            descriptor.get("contract_version") != 3
            and descriptor.get("camera_contract_revision") not in (REVISION, MEDIA11)
        ) or descriptor["source_type"] != "camera":
            raise ValueError("negotiated_camera_descriptor_required")
        modern = value["contract_version"] == 3
        if modern and media_lease is None:
            raise ValueError("camera_media_clock_required")
        if (
            lease.scope != "stream"
            or (
                getattr(lease, "revoked_reason", None) is not None
                if modern
                else not lease.is_active()
            )
            or str(lease.lease_id) != value["lease_id"]
            or lease.sn != value["publisher"]["sn"]
            or (
                value["lease_expires_at"] > media_lease.media_lease_expires_at
                if modern
                else value["lease_expires_at"] != int(lease.expires_at.timestamp())
            )
        ):
            raise ValueError("camera_lease_mismatch")
        if value["lease_expires_at"] * 1000 <= (
            media_lease.coordinate_now_ms
            if modern
            else now_ms if now_ms is not None else int(time.time() * 1000)
        ):
            raise ValueError("camera_lease_expired")
        return cls(
            json.dumps(value, sort_keys=True, separators=(",", ":")),
            media_clock_id=media_lease.media_clock_id if modern else None,
        )

    @property
    def start(self) -> dict:
        return json.loads(self.start_json)

    @property
    def identity(self) -> dict:
        start = self.start
        return {
            "contract_version": start["contract_version"],
            "sn": start["publisher"]["sn"],
            "session_id": start["session_id"],
            "lease_id": start["lease_id"],
            "stream_instance_id": start["publisher"]["stream_instance_id"],
            "descriptor_revision": start["descriptor"]["descriptor_revision"],
        }

    def check_response(self, value: dict) -> None:
        start = self.start
        for key in (
            "session_id",
            "lease_id",
            "operation_id",
            "publisher",
            "descriptor",
        ):
            if value[key] != start[key]:
                raise ValueError("camera_media_epoch_mismatch")
        if value["stream_instance_id"] != start["publisher"]["stream_instance_id"]:
            raise ValueError("camera_media_epoch_mismatch")
        if (
            self.route_generation is not None
            and value["route_generation"] != self.route_generation
        ):
            raise ValueError("camera_media_route_mismatch")


class CameraMediaAdapter:
    def __init__(
        self,
        client: httpx.AsyncClient,
        service_token: str,
        *,
        selection: dict | None = None,
    ):
        if not service_token:
            raise ValueError("media_service_auth_required")
        if selection is not None and selection not in (
            SELECTED,
            SELECTED3,
            SELECTED4,
            SELECTED5,
        ):
            raise ValueError("camera11_incomplete_revision_bundle")
        self.revision = (
            MEDIA14
            if selection == SELECTED5
            else (
                MEDIA13
                if selection == SELECTED4
                else (
                    MEDIA12
                    if selection == SELECTED3
                    else MEDIA11 if selection is not None else REVISION
                )
            )
        )
        self.client = client
        self.headers = {
            "X-L4-Camera-Contract": REVISION,
            "X-Media-Service-Token": service_token,
        }
        if selection in (SELECTED3, SELECTED4, SELECTED5):
            # MEDIA is source-symmetric. Camera admission headers stop at IoT/BFF.
            self.headers = {
                "X-L4-Media-Contract": MEDIA3,
                "X-Media-Service-Token": service_token,
            }
        elif selection is not None:
            self.headers.update(headers11())

    def require_epoch(self, epoch: CameraEpoch) -> None:
        if (epoch.start["contract_version"] == 3) != (
            self.revision in (MEDIA12, MEDIA13, MEDIA14)
        ) or (
            self.revision not in (MEDIA12, MEDIA13, MEDIA14)
            and epoch.start["descriptor"].get("camera_contract_revision")
            != self.revision
        ):
            raise ValueError("camera_media_selection_mismatch")

    async def _call(
        self, path: str, definition: str, *, payload=None, params=None, method="POST"
    ):
        try:
            response = await self.client.request(
                method,
                path,
                headers=self.headers,
                json=payload,
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            if len(response.content) > 32768:
                raise ValueError("media_response_too_large")
            from core.remote_input.video_wire import load_object

            value = load_object(response.content)
            return validate_media(definition, value, self.revision)
        except httpx.HTTPError, ValueError, TypeError:
            # Service rejection bodies, token, PIN and credential material are private.
            raise ValueError("camera_media_request_failed") from None

    async def capabilities(self) -> dict:
        value = await self._call(
            "/api/v2/media/capabilities", "media_capabilities", method="GET"
        )
        if self.revision in (MEDIA12, MEDIA13, MEDIA14):
            if (
                value.get("contract_version") != 3
                or 3 not in value.get("media_contract_versions", [])
                or not value["dependencies_ready"]
            ):
                raise ValueError("media_camera_contract_unavailable")
            return value
        if (
            self.revision not in value.get("camera_contract_revisions", [])
            or not value.get("camera_formats")
            or not value["dependencies_ready"]
        ):
            raise ValueError("media_camera_contract_unavailable")
        if self.revision == MEDIA11 and any(
            value.get(key) != expected for key, expected in CAPABILITIES.items()
        ):
            raise ValueError("camera_media_selection_mismatch")
        return value

    async def prepare(
        self, epoch: CameraEpoch, *, media_lease=None
    ) -> tuple[CameraEpoch, dict]:
        # No firmware command is emitted here. Capability resolution and the actual
        # SPS-derived descriptor must already have completed before media prepare.
        self.require_epoch(epoch)
        if self.revision in (MEDIA12, MEDIA13, MEDIA14):
            if (
                media_lease is None
                or media_lease.media_clock_id != epoch.media_clock_id
                or epoch.start["lease_expires_at"] > media_lease.media_lease_expires_at
                or epoch.start["lease_expires_at"] * 1000
                <= media_lease.coordinate_now_ms
            ):
                raise ValueError("camera_media_clock_mismatch_or_expired")
        elif epoch.start["lease_expires_at"] <= time.time():
            raise ValueError("camera_lease_expired")
        capabilities = await self.capabilities()
        require_server_format(capabilities, epoch.start["descriptor"])
        try:
            response = await self._call(
                "/api/v2/media/sessions/start", "media_response", payload=epoch.start
            )
            epoch.check_response(response)
            if response["state"] not in ("starting", "active"):
                raise ValueError("camera_media_start_failed")
        except ValueError, httpx.HTTPError:
            try:
                await self.stop(epoch, "prepare_failed")
            except ValueError:
                pass  # The immutable server lease deadline remains the final cleanup.
            raise
        return (
            CameraEpoch(
                epoch.start_json, response["route_generation"], epoch.media_clock_id
            ),
            response,
        )

    async def health(self, epoch: CameraEpoch) -> dict:
        self.require_epoch(epoch)
        response = await self._call(
            f"/api/v2/media/sessions/{epoch.identity['session_id']}",
            "media_health",
            params={
                key: value
                for key, value in epoch.identity.items()
                if key not in ("contract_version", "session_id")
            },
            method="GET",
        )
        epoch.check_response(response)
        return response  # READY, RTP freshness and browser decode remain separate.

    async def renew(self, epoch: CameraEpoch, lease, *, media_lease=None) -> dict:
        self.require_epoch(epoch)
        modern = self.revision in (MEDIA12, MEDIA13, MEDIA14)
        if (
            (lease.revoked_reason is not None if modern else not lease.is_active())
            or lease.scope != "stream"
            or lease.sn != epoch.identity["sn"]
            or str(lease.lease_id) != epoch.identity["lease_id"]
        ):
            raise ValueError("camera_lease_mismatch")
        if modern and (
            media_lease is None
            or media_lease.media_clock_id != epoch.media_clock_id
            or media_lease.media_remaining_ms <= 0
            or media_lease.media_lease_expires_at * 1000
            <= media_lease.coordinate_now_ms
        ):
            raise ValueError("camera_media_clock_mismatch_or_expired")
        payload = {
            **epoch.identity,
            "lease_expires_at": (
                media_lease.media_lease_expires_at
                if modern
                else int(lease.expires_at.timestamp())
            ),
        }
        validate_media("media_renew", payload, self.revision)
        response = await self._call(
            "/api/v2/media/sessions/renew", "media_response", payload=payload
        )
        epoch.check_response(response)
        return response

    async def stop(self, epoch: CameraEpoch, reason: str) -> dict:
        self.require_epoch(epoch)
        payload = {**epoch.identity, "reason": reason}
        validate_media("media_stop", payload, self.revision)
        response = await self._call(
            "/api/v2/media/sessions/stop", "media_response", payload=payload
        )
        epoch.check_response(response)
        return response
