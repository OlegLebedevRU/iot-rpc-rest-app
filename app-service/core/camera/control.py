"""Camera-specific publisher epochs on the inspected existing siplite CTL v1."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, RootModel, model_validator, UUID4

from core.camera.contract import REVISION
from core.camera.native_contract import (
    MEDIA11,
    MEDIA12,
    MEDIA13,
    MEDIA14,
    MEDIA3,
    CADENCE,
    SELECTED,
    SELECTED3,
    SELECTED4,
    SELECTED5,
    CADENCE02,
    CADENCE03,
    modern_selection,
    validate_media,
    selection_for_descriptor,
)
from core.camera.media import CameraEpoch
from core.camera.producer import start_command, stop_command
from core.camera.projection import camera_capability
from core.remote_input.video_control import LIVE, video_control


class CameraStart(RootModel[dict[str, Any]]):
    @model_validator(mode="before")
    @classmethod
    def validate_body(cls, value):
        parsed = validate_media("media_start", value)
        if parsed["descriptor"]["source_type"] != "camera":
            raise ValueError("camera_source_type_required")
        return parsed


class CameraStop(RootModel[dict[str, Any]]):
    @model_validator(mode="before")
    @classmethod
    def validate_body(cls, value):
        return validate_media("media_stop", value)


class CameraStateView(BaseModel):
    camera_contract_revision: Literal["siplite-camera/1.0.0"] = REVISION
    version: Literal[2] = 2
    sn: str
    lease_id: str
    operation_id: str
    command_id: str
    stream_instance_id: str
    descriptor: dict[str, Any]
    resolved_codec: Literal["h264", "h265"]
    result: str
    state: str
    confirmation: Literal["command_ack"] | None = None
    actual_descriptor: None = None
    reason: str | None = None

    @classmethod
    def from_record(cls, record: dict):
        start = record["start"]
        model = (
            (
                CameraStateView14
                if record.get("selection") == SELECTED5
                else (
                    CameraStateView13
                    if record.get("selection") == SELECTED4
                    else CameraStateView12
                )
            )
            if start["contract_version"] == 3
            else (
                CameraStateView11
                if start["descriptor"].get("camera_contract_revision") == MEDIA11
                else cls
            )
        )
        return model(
            sn=start["publisher"]["sn"],
            lease_id=start["lease_id"],
            operation_id=start["operation_id"],
            command_id=start["operation_id"],
            stream_instance_id=start["publisher"]["stream_instance_id"],
            descriptor=start["descriptor"],
            resolved_codec=start["descriptor"]["tracks"][0]["codec"],
            result=record["result"],
            state=record["state"],
            confirmation=record.get("confirmation"),
            reason=record.get("reason"),
            **(
                {"media_clock_id": record["media_clock_id"]}
                if start["contract_version"] == 3
                else {}
            ),
        )


class CameraStateView11(CameraStateView):
    camera_contract_revision: Literal["siplite-camera/1.1.0"] = MEDIA11
    cadence_revision: Literal["camera-cadence/0.1.0-proposed"] = CADENCE


class CameraStateView12(CameraStateView11):
    camera_contract_revision: Literal["siplite-camera/1.2.0"] = MEDIA12
    contract_version: Literal[3] = 3
    media_contract_revision: Literal["l4-media/3.0.0"] = MEDIA3
    media_clock_id: UUID4


class CameraStateView13(CameraStateView12):
    camera_contract_revision: Literal["siplite-camera/1.3.0"] = MEDIA13
    cadence_revision: Literal["camera-cadence/0.2.0-proposed"] = CADENCE02


class CameraStateView14(CameraStateView12):
    camera_contract_revision: Literal["siplite-camera/1.4.0"] = MEDIA14
    cadence_revision: Literal["camera-cadence/0.3.0-proposed"] = CADENCE03


def epoch_of(record: dict) -> CameraEpoch:
    return CameraEpoch(
        json.dumps(record["start"], sort_keys=True, separators=(",", ":")),
        media_clock_id=record.get("media_clock_id"),
    )


class CameraControl:
    async def publisher_lease(self, service, identity, pipe):
        from core.camera.media_clock import camera_media_clock

        raw = await pipe.hgetall(f"l4d:lease:{identity['lease_id']}")
        if camera_media_clock.scoped(raw) or identity.get("contract_version") == 3:
            return await camera_media_clock.publisher_lease(service, identity, pipe)
        return await video_control.publisher_lease(service, identity, pipe)

    async def record(self, sn: str) -> dict | None:
        return (await video_control.store.get(sn)).get("camera_stream")

    async def update(
        self,
        epoch: CameraEpoch,
        expected_states: tuple | None = None,
        authority_service=None,
        **changes,
    ) -> dict | None:
        valid = True

        async def guard(pipe, document):
            nonlocal valid
            lease = await self.publisher_lease(authority_service, epoch.identity, pipe)
            valid = (
                lease is not None
                and str(lease.stream_instance_id)
                == epoch.identity["stream_instance_id"]
            )

        def apply(doc):
            record = doc.get("camera_stream")
            if (
                valid
                and record
                and epoch_of(record).identity == epoch.identity
                and (expected_states is None or record["state"] in expected_states)
            ):
                record.update(**changes)
                return record
            return None

        return await video_control.store.change(
            epoch.identity["sn"],
            apply,
            guard=guard if authority_service is not None else None,
        )

    async def clear_lease(self, service, epoch: CameraEpoch) -> None:
        lease = await service.leases.get(UUID(epoch.identity["lease_id"]))
        stream = UUID(epoch.identity["stream_instance_id"])
        if lease and lease.stream_instance_id == stream:
            lease.stream_instance_id = None
            lease.stream_state = "stopped"
            lease.stream_mode = None
            lease.selected_camera_id = None
            if epoch.start["contract_version"] == 3:
                from core.camera.media_clock import camera_media_clock

                await camera_media_clock.save_stream(lease, stream)
            else:
                await service.leases.save_stream(lease, stream)
            record = await self.record(epoch.identity["sn"])
            if (
                record
                and record.get("admission_revision")
                and epoch_of(record).identity == epoch.identity
            ):
                # The negotiated profile requires fresh lease/stream IDs per attempt.
                await service.leases.revoke(lease.lease_id, "camera_attempt_retired")

    async def start(
        self,
        service,
        session_db,
        lease,
        payload: dict,
        send,
        *,
        monotonic: bool = False,
        readiness_nonce: str | None = None,
        selected: dict | None = None,
    ) -> dict:
        await self.reconcile(lease.sn, service, send)
        from core.camera.media_clock import camera_media_clock

        modern = payload.get("contract_version") == 3
        media_lease = await camera_media_clock.export(lease) if modern else None
        epoch = CameraEpoch.from_start(payload, lease, media_lease=media_lease)
        selection = (
            selected
            if selected is not None
            else selection_for_descriptor(epoch.start["descriptor"])
        )
        native = selection is not None
        if native and not monotonic:
            raise HTTPException(422, "camera11_incomplete_revision_bundle")
        view = await camera_capability(
            session_db,
            lease.device_id,
            authorized_sn=lease.sn,
            **(
                {
                    "native": True,
                    "media_version": epoch.start["contract_version"],
                    **(
                        {"camera_revision": selection["camera_contract_revision"]}
                        if selection in (SELECTED4, SELECTED5)
                        else {}
                    ),
                }
                if native
                else {}
            ),
        )
        if not view.producer_adapter["ready"]:
            raise HTTPException(409, view.producer_adapter["reason"])
        current_ms = int(time.time() * 1000)
        command = start_command(
            epoch,
            view.camera,
            media_lease.coordinate_now_ms if modern else current_ms,
            **(
                {"observation": view.camera_observation, "selection": selection}
                if native
                else {}
            ),
        )
        from core.config import settings

        if settings.camera.monotonic_runtime_enabled:
            from core.camera.runtime import camera_runtime
            from core.camera.runtime_admission import configuration

            durable = await camera_runtime.store.get(lease.sn)
            configured = durable.get("configured")
            if configured:
                if not monotonic:
                    raise HTTPException(409, "camera_runtime_revision_required")
                actual = configuration(
                    view.camera,
                    epoch.start["descriptor"],
                    configured["binding"]["physical_camera_mac"],
                    **(
                        {"observation": view.camera_observation, "selection": selection}
                        if native
                        else {}
                    ),
                )
                if actual != configured:
                    raise HTTPException(409, "camera_physical_binding_changed")
            elif monotonic:
                raise HTTPException(409, "camera_binding_not_prepared")
        # PIN belongs only to BFF/media. Do not retain or send it to firmware.
        stored_start = epoch.start
        stored_start.pop("pin", None)
        epoch = CameraEpoch(
            json.dumps(stored_start, sort_keys=True, separators=(",", ":")),
            media_clock_id=epoch.media_clock_id,
        )

        def reserve(doc):
            active = doc.get("camera_stream")
            if (
                active
                and active["start"] == stored_start
                and active.get(
                    "selection", selection_for_descriptor(active["start"]["descriptor"])
                )
                == selection
            ):
                return {**active, "replayed": True}
            if (active and active["state"] in LIVE) or doc.get("stream", {}).get(
                "state"
            ) in LIVE:
                raise HTTPException(409, "stream_conflict")
            if (
                lease.stream_instance_id is not None
                or doc.get("legacy_pending", {}).get("expires_at_ms", 0) > current_ms
            ):
                raise HTTPException(409, "stream_conflict")
            record = {
                "start": stored_start,
                "state": "starting",
                "result": "accepted",
                "confirmation": None,
            }
            if modern:
                record["media_clock_id"] = media_lease.media_clock_id
            if native:
                record["selection"] = selection
            if monotonic:
                from core.camera.runtime_wire import ADMISSION

                record["admission_revision"] = ADMISSION
            doc["camera_stream"] = record
            return record

        async def guard(pipe, doc):
            authoritative = await self.publisher_lease(service, epoch.identity, pipe)
            if (
                authoritative is None
                or authoritative.scope != "stream"
                or authoritative.owner_user_id != lease.owner_user_id
                or authoritative.owner_session_id != lease.owner_session_id
                or (
                    not modern
                    and int(authoritative.expires_at.timestamp())
                    < stored_start["lease_expires_at"]
                )
            ):
                raise HTTPException(409, "lease_invalid")

        record = await video_control.store.change(
            lease.sn,
            reserve,
            claim=(str(command.stream_instance_id), str(command.command_id)),
            guard=guard,
        )
        if record.get("replayed"):
            return record
        lease.stream_instance_id = command.stream_instance_id
        lease.stream_mode = "usb-camera"
        lease.selected_camera_id = command.source_id
        # The publisher epoch is negotiated media v2; only the firmware adapter is CTL v1.
        lease.stream_contract_version = epoch.start["contract_version"]
        lease.stream_state = "starting"
        if not await (
            camera_media_clock.save_stream(lease, None)
            if modern
            else service.leases.save_stream(lease, None)
        ):
            await self.update(
                epoch, state="failed", result="failed", reason="lease_invalid"
            )
            raise HTTPException(409, "lease_invalid")
        timeout = min(
            15.0,
            (
                (
                    stored_start["lease_expires_at"] * 1000
                    - media_lease.coordinate_now_ms
                )
                / 1000
                if modern
                else stored_start["lease_expires_at"] - time.time()
            ),
        )
        try:
            if timeout <= 0:
                raise ValueError("camera_lease_expired")
            if monotonic:
                from core.camera.runtime import camera_runtime

                command = await camera_runtime.command(
                    "start", epoch, lease, readiness_nonce
                )
            future = (
                None
                if monotonic
                else await service.pending.register(
                    command.command_id,
                    lease.lease_id,
                    lease.sn,
                    "stream_start",
                    timeout_sec=timeout,
                )
            )
            await asyncio.wait_for(
                send(
                    lease.sn, command, ttl_ms=max(1, command.expires_at_ms - current_ms)
                ),
                timeout=5,
            )
            ack = (
                await camera_runtime.wait_ack(command, timeout)
                if monotonic
                else await asyncio.wait_for(future, timeout=timeout)
            )
            if (
                ack.result not in ("started", "already_running")
                or ack.stream_instance_id != command.stream_instance_id
            ):
                raise ValueError("camera_start_unconfirmed")
            # The ACK asserts relay lifecycle only. It is never labelled agent_ready,
            # fresh RTP, exact post-START descriptor, or browser decoded frames.
            record = await self.update(
                epoch,
                expected_states=("starting", "running"),
                authority_service=service,
                state="running",
                result=ack.result,
                confirmation="command_ack",
            )
            if record is None:
                raise ValueError("camera_epoch_replaced")
            return record
        except Exception, asyncio.CancelledError:
            await self.update(
                epoch,
                expected_states=LIVE,
                state="failed",
                result="failed",
                reason="camera_start_unconfirmed",
            )
            await self.clear_lease(service, epoch)
            try:
                command_stop = (
                    await camera_runtime.command("stop", epoch)
                    if monotonic
                    else stop_command(epoch, int(time.time() * 1000))
                )
                await asyncio.wait_for(
                    send(lease.sn, command_stop, ttl_ms=5000), timeout=5
                )
            except Exception:
                pass  # Both firmware and media retain the authoritative deadline.
            raise

    async def stop(self, service, lease, payload: dict, send) -> dict:
        record = await self.record(lease.sn)
        if not record:
            raise HTTPException(404, "camera_state_not_found")
        epoch = epoch_of(record)
        if {key: payload[key] for key in epoch.identity} != epoch.identity:
            raise HTTPException(409, "camera_epoch_mismatch")
        if record["state"] not in LIVE:
            return record
        await self.update(epoch, state="stopping", result="stopping")
        if record.get("admission_revision"):
            from core.camera.runtime import camera_runtime

            try:
                command = await camera_runtime.command("stop", epoch)
            except ValueError as exc:
                if str(exc) != "camera_stream_not_live":
                    raise
                await self.update(
                    epoch, state="stopped", result="stopped", reason="lease_invalid"
                )
                await self.clear_lease(service, epoch)
                return await self.record(lease.sn)
        else:
            command = stop_command(epoch, int(time.time() * 1000))
        await asyncio.wait_for(send(lease.sn, command, ttl_ms=5000), timeout=5)
        # Wait for terminal evidence/watchdog; publication is not STOP completion.
        return await self.record(lease.sn)

    async def event(self, sn: str, event, service) -> bool:
        record = await self.record(sn)
        if not record:
            return False
        epoch = epoch_of(record)
        if (
            event.sn not in (None, sn)
            or str(event.stream_instance_id) != epoch.identity["stream_instance_id"]
        ):
            return False
        lease = await service.leases.get(UUID(epoch.identity["lease_id"]))
        live_lease = lease is not None and lease.is_active()
        if lease is not None and epoch.start["contract_version"] == 3:
            from core.camera.media_clock import camera_media_clock

            try:
                await camera_media_clock.export(lease)
                live_lease = True
            except ValueError:
                live_lease = False
        if event.state == "running":
            # Late running must not revive a retired epoch.
            if record["state"] not in ("starting", "running") or not live_lease:
                return False
            await service.presence.notify_video_event(event)
            return True
        if event.state in (
            "stopped",
            "failed",
            "source_unavailable",
            "session_unavailable",
        ):
            if record.get("admission_revision"):
                from core.camera.runtime import camera_runtime

                await camera_runtime.submit(
                    sn,
                    "retire",
                    {k: epoch.identity[k] for k in ("lease_id", "stream_instance_id")},
                )
            state = "stopped" if event.state == "stopped" else "failed"
            await self.update(epoch, state=state, result=state, reason=event.reason)
            await self.clear_lease(service, epoch)
            await service.presence.notify_video_event(event)
            return True
        return False

    async def reconcile(self, sn: str, service, send) -> bool:
        orphan = False

        async def guard(pipe, document):
            nonlocal orphan
            record = document.get("camera_stream")
            orphan = False
            if record and record["state"] in LIVE:
                identity = epoch_of(record).identity
                lease = await self.publisher_lease(service, identity, pipe)
                orphan = (
                    lease is None
                    or lease.scope != "stream"
                    or str(lease.stream_instance_id) != identity["stream_instance_id"]
                )
                if not orphan and record.get("admission_revision"):
                    from core.camera.runtime import camera_runtime
                    from core.camera.runtime_admission import configuration
                    from core.models import db_helper

                    durable = await camera_runtime.store.get(sn)
                    configured = durable.get("configured")
                    selection = configured.get("selection") if configured else None
                    async with db_helper.session_factory() as session:
                        view = await camera_capability(
                            session,
                            lease.device_id,
                            authorized_sn=sn,
                            **(
                                {
                                    "native": True,
                                    "media_version": (
                                        3 if modern_selection(selection) else 2
                                    ),
                                    **(
                                        {
                                            "camera_revision": selection[
                                                "camera_contract_revision"
                                            ]
                                        }
                                        if selection in (SELECTED4, SELECTED5)
                                        else {}
                                    ),
                                }
                                if selection
                                in (SELECTED, SELECTED3, SELECTED4, SELECTED5)
                                else {}
                            ),
                        )
                    try:
                        orphan = (
                            not view.main_app_online
                            or not view.fresh
                            or not configured
                            or configuration(
                                view.camera,
                                configured["descriptor"],
                                configured["binding"]["physical_camera_mac"],
                                **(
                                    {
                                        "observation": view.camera_observation,
                                        "selection": selection,
                                    }
                                    if selection
                                    in (SELECTED, SELECTED3, SELECTED4, SELECTED5)
                                    else {}
                                ),
                            )
                            != configured
                            or (
                                durable["active"] is None
                                and (
                                    record["state"] == "running"
                                    or durable["ready"] is None
                                )
                            )
                        )
                    except ValueError, TypeError:
                        orphan = True

        def retire(document):
            record = document.get("camera_stream")
            if not orphan or not record or record["state"] not in LIVE:
                return None
            record.update(state="stopped", result="stopped", reason="lease_invalid")
            return record

        record = await video_control.store.change(sn, retire, guard=guard)
        if record is None:
            return False
        epoch = epoch_of(record)
        await self.clear_lease(service, epoch)
        from core.remote_input.schemas import CtlStreamEvent
        from datetime import UTC, datetime

        await service.presence.notify_video_event(
            CtlStreamEvent(
                sn=sn,
                stream_instance_id=UUID(epoch.identity["stream_instance_id"]),
                state="stopped",
                reason="lease_invalid",
                timestamp=datetime.now(UTC).isoformat(),
            )
        )
        try:
            if record.get("admission_revision"):
                from core.camera.runtime import camera_runtime

                command = await camera_runtime.command("stop", epoch)
            else:
                command = stop_command(epoch, int(time.time() * 1000))
            await asyncio.wait_for(send(sn, command, ttl_ms=5000), timeout=5)
        except Exception:
            pass
        return True

    async def cleanup(self, service, send) -> None:
        async for key in video_control.store.client.scan_iter(match="l4d:video:v2:*"):
            sn = key.removeprefix("l4d:video:v2:")
            if ":" not in sn:
                await self.reconcile(sn, service, send)


camera_control = CameraControl()
