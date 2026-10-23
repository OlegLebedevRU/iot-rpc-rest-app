"""Negotiated video control. V2 records never enter legacy Redis namespaces."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, NoReturn
from uuid import UUID, uuid4

from fastapi import HTTPException
from redis.exceptions import WatchError

from core.config import settings
from core.redis_helper import redis_helper
from core.remote_input import video_models as wire
from core.remote_input.schemas import CtlStreamEvent, StreamState

if TYPE_CHECKING:
    from core.remote_input.leases import Lease

# A cached ready from a previous server process cannot authorize a publisher.
SERVER_EPOCH = str(uuid4())
LIVE = ("starting", "running", "stopping")
IDENTITY = (
    "lease_id",
    "stream_instance_id",
    "operation_id",
    "agent_instance_id",
    "resolved_codec",
    "descriptor",
    "delivery",
    "recovery_policy",
)
log = logging.getLogger(__name__)


def now_ms() -> int:
    return int(time.time() * 1000)


def reject(code: str, status: int = 409) -> NoReturn:
    raise HTTPException(status_code=status, detail={"code": code})


class VideoStore:
    """One transactional document/SN: capability, pending query and publisher epoch."""

    @property
    def client(self):
        return redis_helper.get_client()

    def key(self, sn: str) -> str:
        return f"l4d:video:v2:{sn}"

    async def current_epoch(self) -> str:
        await self.client.set("l4d:video:server-epoch", SERVER_EPOCH, nx=True)
        return await self.client.get("l4d:video:server-epoch")

    async def reset_server_epoch(self) -> None:
        # Worker startup invalidates old negotiation for all workers, while
        # retaining live publisher identities for event handling and drain.
        await self.client.set("l4d:video:server-epoch", str(uuid4()))

    async def get(self, sn: str) -> dict[str, Any]:
        raw = await self.client.get(self.key(sn))
        return self.decode(raw)

    def decode(self, raw: str | None) -> dict[str, Any]:
        document = json.loads(raw) if raw else {}
        if not isinstance(document, dict):
            reject("invalid_payload", 400)
        if document.get("capability") is not None:
            wire.Capabilities.model_validate(document["capability"])
        state = document.get("stream")
        if state is not None:
            if state.get("version") != 2 or "descriptor" not in state.get("start", {}):
                reject("invalid_payload", 400)
            wire.Start.model_validate(state["start"])
        if document.get("camera_stream") is not None:
            from core.camera.contract import validate_definition

            validate_definition(
                "hevc.schema.json", "media_start", document["camera_stream"]["start"]
            )
        return document

    async def change(
        self,
        sn: str,
        apply: Callable[[dict[str, Any]], Any],
        claim: tuple[str, str] | None = None,
        expected_epoch: str | None = None,
        guard: Callable[[Any, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> Any:
        key = self.key(sn)
        claim_keys = (
            [
                f"{key}:{kind}:{value}"
                for kind, value in zip(("stream", "operation"), claim)
            ]
            if claim
            else []
        )
        for _ in range(10):
            async with self.client.pipeline(transaction=True) as pipe:
                try:
                    await pipe.watch(key, *claim_keys, "l4d:video:server-epoch")
                    if (
                        expected_epoch is not None
                        and await pipe.get("l4d:video:server-epoch") != expected_epoch
                    ):
                        reject("stale_capability")
                    raw = await pipe.get(key)
                    doc = self.decode(raw)
                    before = json.dumps(doc, separators=(",", ":"))
                    if guard is not None:
                        await guard(pipe, doc)
                    result = apply(doc)
                    if json.dumps(doc, separators=(",", ":")) == before:
                        return result
                    state = doc.get("stream", {})
                    deadline = state.get("start", {}).get("lease_expires_at_ms", 0)
                    ttl = max(300, int((deadline - now_ms()) / 1000) + 300)
                    reserve = claim and result.get("result") == "accepted"
                    if reserve and any([await pipe.exists(k) for k in claim_keys]):
                        reject("conflict")
                    pipe.multi()
                    if reserve:
                        for claim_key in claim_keys:
                            pipe.set(claim_key, "1", ex=ttl)
                    if state:
                        start = state["start"]
                        for kind, value in (
                            ("stream", start["stream_instance_id"]),
                            ("operation", start["operation_id"]),
                        ):
                            pipe.expire(f"{key}:{kind}:{value}", ttl)
                    pipe.set(key, json.dumps(doc, separators=(",", ":")), ex=ttl)
                    await pipe.execute()
                    return result
                except WatchError:
                    continue
        reject("busy")


def select_codec(start: dict[str, Any], context: dict[str, Any]) -> str:
    """PREPARE decision; an h264 result does not authorize an HEVC candidate."""
    if not context["authorized"]:
        return "unauthorized"
    if (
        not context["tenant_matches"]
        or not context["source_allowed"]
        or start["sn"] != context["sn"]
    ):
        return "forbidden"
    if not context["lease_active"]:
        return "lease_invalid"
    if start["lease_id"] != context["lease_id"]:
        return "lease_mismatch"
    if (
        not 0 < start["expires_at_ms"] - start["issued_at_ms"] <= 30000
        or start["expires_at_ms"] > start["lease_expires_at_ms"]
    ):
        return "invalid_payload"
    if (
        not start["issued_at_ms"]
        <= context["now_ms"]
        < min(start["expires_at_ms"], start["lease_expires_at_ms"])
    ):
        return "expired"
    active = context.get("active_start")
    if active:
        return (
            "already_running"
            if all(start[k] == active[k] for k in IDENTITY)
            else "conflict"
        )
    if not context["negotiated_v2"]:
        return "unsupported"
    cap = context["capabilities"]
    if (
        start["agent_instance_id"] != context["agent_instance_id"]
        or cap["agent_instance_id"] != context["agent_instance_id"]
        or start["capability_revision"] != cap["capability_revision"]
        or start["descriptor"]["source_id"] != cap["source_id"]
        or start["descriptor"]["geometry_generation"]
        != cap["binding"]["geometry_generation"]
        or context["binding"] != cap["binding"]
    ):
        return "capability_mismatch"
    if start["codec_policy"] == "h264":
        return "h264"
    if (
        not 0 < cap["valid_until_ms"] - cap["checked_at_ms"] <= 60000
        or not cap["checked_at_ms"] <= context["now_ms"] < cap["valid_until_ms"]
    ):
        return "h264" if start["codec_policy"] == "auto" else "stale_capability"
    supported = context["server_hevc_ready"] and any(
        entry["codec"] == "h265"
        and (
            (entry["backend"] == "media_foundation" and entry["hardware"])
            or (
                context.get("test_camera_source", False)
                and entry["backend"] == "camera"
                and start["descriptor"]["source_type"] == "usb-camera"
                and start["descriptor"]["source_id"].startswith("test-")
            )
        )
        and entry["status"] == "ready"
        and entry["probe_evidence"] == "encoded_sequence"
        and any(
            p["profile_id"] == start["descriptor"]["profile_id"]
            and p["track"] == start["descriptor"]["tracks"][0]
            for p in entry["profiles"]
        )
        for entry in cap["video"]
    )
    if supported:
        return "h265"
    return "h264" if start["codec_policy"] == "auto" else "unsupported"


class VideoControl:
    def __init__(self, store: VideoStore | None = None) -> None:
        self.store = store or VideoStore()

    async def get_lease(self, service: Any, lease_id: UUID) -> Lease | None:
        from core.remote_input.leases import RedisLeaseRegistry, _dict_to_lease

        if isinstance(service.leases, RedisLeaseRegistry):
            data = await self.store.client.hgetall(f"l4d:lease:{lease_id}")
            return _dict_to_lease(data) if data else None
        return await service.leases.get(lease_id)

    async def publisher_lease(
        self, service: Any, start: dict[str, Any], pipe: Any
    ) -> Lease | None:
        """Read authority under the video transaction, never a worker cache.

        Watching both keys fences renew/revoke/replacement and Redis expiry.
        The in-memory registry is retained for single-process integrations.
        """
        from core.remote_input.leases import RedisLeaseRegistry, _dict_to_lease

        if isinstance(service.leases, RedisLeaseRegistry):
            key = f"l4d:lease:{start['lease_id']}"
            active = f"l4d:lease:active:{start['sn']}"
            await pipe.watch(key, active)
            data = await pipe.hgetall(key)
            if not data or await pipe.get(active) != start["lease_id"]:
                return None
            lease = _dict_to_lease(data)
        else:
            lease = await service.leases.get(UUID(start["lease_id"]))
        if not lease or not lease.is_active() or lease.sn != start["sn"]:
            return None
        return lease

    async def reconcile(self, sn: str, service: Any, send: Any) -> bool:
        """Retire only a LIVE epoch whose publisher lease lost authority."""
        orphan = False

        async def guard(pipe: Any, doc: dict[str, Any]) -> None:
            nonlocal orphan
            state = doc.get("stream")
            orphan = bool(
                state
                and state["state"] in LIVE
                and await self.publisher_lease(service, state["start"], pipe) is None
            )

        def retire(doc: dict[str, Any]) -> dict[str, Any] | None:
            if not orphan:
                return None
            state = doc["stream"]
            state.update(state="stopped", result="stopped", reason="lease_invalid")
            return state

        state = await self.store.change(sn, retire, guard=guard)
        if state is None:
            return False
        await self.clear_lease(service, sn, state)
        await self.notify(
            service,
            sn,
            state["start"]["stream_instance_id"],
            "stopped",
            "lease_invalid",
        )
        try:
            await self.stop_command(state, send)
        except Exception:
            log.warning("V2 orphan STOP publication failed", exc_info=True)
        return True

    async def cleanup(self, service: Any, send: Any) -> None:
        # Do not discover expiry through active lease keys: those expire first.
        async for key in self.store.client.scan_iter(match="l4d:video:v2:*"):
            sn = key.removeprefix("l4d:video:v2:")
            if ":" not in sn:
                await self.reconcile(sn, service, send)

    @asynccontextmanager
    async def legacy_start(self, lease: Any, mode: str, source: str, profile: str):
        """Serialize old writers with each other and with concrete v2 reservation."""
        token = str(uuid4())
        identity = [str(lease.lease_id), mode, source, profile]
        deadline = now_ms() + 30000
        while True:

            def reserve(doc: dict[str, Any]) -> bool:
                if doc.get("camera_stream", {}).get("state") in LIVE:
                    raise HTTPException(409, "stream_conflict")
                pending = doc.get("legacy_pending", {})
                if pending.get("expires_at_ms", 0) > now_ms():
                    if pending["identity"] != identity:
                        raise HTTPException(status_code=409, detail="stream_conflict")
                    return False
                doc["legacy_pending"] = {
                    "token": token,
                    "identity": identity,
                    "expires_at_ms": deadline,
                }
                return True

            if await self.store.change(lease.sn, reserve):
                break
            if now_ms() >= deadline:
                raise HTTPException(status_code=409, detail="stream_conflict")
            await asyncio.sleep(0.05)
        try:
            yield
        finally:

            def release(doc: dict[str, Any]) -> None:
                if doc.get("legacy_pending", {}).get("token") == token:
                    doc.pop("legacy_pending", None)

            await self.store.change(lease.sn, release)

    async def observe_presence(self, sn: str, presence: Any) -> None:
        signature = [
            presence.session_id,
            presence.desktop_available,
            presence.version,
            presence.screen.model_dump() if presence.screen else None,
            presence.inventory.model_dump() if presence.inventory else None,
            presence.capabilities,
        ]

        def update(doc: dict[str, Any]) -> None:
            if (
                doc.get("presence") != signature
                or presence.status != "online"
                or "video_contract_v2" not in (presence.capabilities or [])
                or not settings.remote_input.video_v2_enabled
            ):
                doc.pop("capability", None)
                doc.pop("pending", None)
            doc["presence"] = signature

        await self.store.change(sn, update)

    async def capability(
        self, sn: str, presence: Any, send: Any, refresh: bool = False
    ) -> dict[str, Any]:
        if not settings.remote_input.video_v2_enabled:
            await self.invalidate(sn)
            return {"negotiated_v2": False, "video_capabilities": None}
        if (
            not settings.remote_input.video_hevc_chain_ready
            and sn not in settings.remote_input.video_test_camera_sns
        ):
            # Close new HEVC negotiation before BFF commits a concrete codec.
            # Keep measured capability and existing v2 traffic/state intact.
            return {"negotiated_v2": False, "video_capabilities": None}
        view = await presence.get(sn)
        if not view.online or "video_contract_v2" not in (view.capabilities or []):
            await self.invalidate(sn)
            return {"negotiated_v2": False, "video_capabilities": None}
        current = now_ms()
        server_epoch = await self.store.current_epoch()
        query = wire.InventoryGet(
            v=2,
            type="inventory_get",
            command_id=str(uuid4()),
            sn=sn,
            issued_at_ms=current,
            # The frozen inventory_get fixture already allows10s. This is
            # capability negotiation, not the stream first-frame budget:
            # hardware activation checks Medium first, then optional HD.
            expires_at_ms=current + 10000,
        )

        def reserve(doc: dict[str, Any]) -> bool:
            cap = doc.get("capability")
            if (
                not refresh
                and cap
                and doc.get("server_epoch") == server_epoch
                and cap["checked_at_ms"] <= current < cap["valid_until_ms"]
            ):
                return False
            if current < doc.get("next_probe_ms", 0):
                return False
            doc.pop("capability", None)
            doc["pending"] = query.model_dump(mode="json")
            doc["next_probe_ms"] = current + 30000
            doc["server_epoch"] = server_epoch
            return True

        if await self.store.change(sn, reserve, expected_epoch=server_epoch):
            try:
                await send(sn, query, ttl_ms=10000)
                while now_ms() < query.expires_at_ms:
                    doc = await self.store.get(sn)
                    if not doc.get("pending"):
                        break
                    await asyncio.sleep(0.05)
            finally:

                def expire(doc: dict[str, Any]) -> None:
                    if doc.get("pending", {}).get("command_id") == query.command_id:
                        doc.pop("pending", None)

                await self.store.change(sn, expire)
        doc = await self.store.get(sn)
        cap = doc.get("capability")
        test_camera = bool(
            cap
            and sn in settings.remote_input.video_test_camera_sns
            and cap.get("source_id", "").startswith("test-")
            and any(entry["backend"] == "camera" for entry in cap.get("video", []))
        )
        fresh = bool(
            cap
            and doc.get("server_epoch") == await self.store.current_epoch()
            and cap["checked_at_ms"] <= now_ms() < cap["valid_until_ms"]
            and (settings.remote_input.video_hevc_chain_ready or test_camera)
        )
        return {"negotiated_v2": fresh, "video_capabilities": cap if fresh else None}

    async def invalidate(self, sn: str) -> None:
        def update(doc: dict[str, Any]) -> None:
            doc.pop("capability", None)
            doc.pop("pending", None)

        await self.store.change(sn, update)

    async def accept_capability(self, sn: str, ack: wire.CapabilitiesAck) -> bool:
        cap = ack.video_capabilities.model_dump(mode="json")
        server_epoch = await self.store.current_epoch()

        def update(doc: dict[str, Any]) -> bool:
            query = doc.get("pending", {})
            if (
                ack.sn != sn
                or doc.get("server_epoch") != server_epoch
                or ack.command_id != query.get("command_id")
                or not query.get("issued_at_ms", 0)
                <= now_ms()
                < query.get("expires_at_ms", 0)
                or not cap["checked_at_ms"] <= now_ms() < cap["valid_until_ms"]
                or not 0 < cap["valid_until_ms"] - cap["checked_at_ms"] <= 60000
            ):
                return False
            # A cached pre-query ready must never complete negotiation.
            if cap["checked_at_ms"] < query["issued_at_ms"]:
                return False
            doc["capability"] = cap
            doc.pop("pending", None)
            return True

        return await self.store.change(sn, update, expected_epoch=server_epoch)

    async def authorize(
        self,
        service: Any,
        lease_id: UUID,
        org_id: int,
        user: str,
        session: str,
        superuser: bool = False,
        require_active: bool = True,
    ) -> Any:
        lease = await self.get_lease(service, lease_id)
        if not lease or (require_active and not lease.is_active()):
            reject("lease_invalid")
        if not superuser and (
            lease.org_id != org_id
            or not user
            or not session
            or lease.owner_user_id != user
            or lease.owner_session_id != session
        ):
            reject("forbidden", 403)
        if lease.scope not in ("stream", "input"):
            reject("forbidden", 403)
        return lease

    async def start(
        self,
        service: Any,
        command: wire.Start,
        org_id: int,
        user: str,
        session: str,
        send: Any,
        superuser: bool = False,
    ) -> dict[str, Any]:
        start = command.model_dump(mode="json")
        lease = await self.authorize(
            service, UUID(command.lease_id), org_id, user, session, superuser
        )
        if command.sn != lease.sn:
            reject("lease_mismatch")
        if not settings.remote_input.video_v2_enabled:
            await self.invalidate(lease.sn)
            reject("unsupported", 422)
        if command.lease_expires_at_ms > int(lease.expires_at.timestamp() * 1000):
            reject("lease_mismatch")
        await self.reconcile(lease.sn, service, send)
        view = await service.presence.get(lease.sn)
        inv = await service.presence.get_inventory(lease.sn)
        descriptor = start["descriptor"]
        test_camera = (
            lease.sn in settings.remote_input.video_test_camera_sns
            and descriptor["source_type"] == "usb-camera"
            and descriptor["source_id"].startswith("test-")
        )
        server_epoch = await self.store.current_epoch()
        if descriptor["source_type"] == "desktop":
            source_allowed = view.desktop_available and any(
                d.desktop_id == descriptor["source_id"]
                and d.policy != "denied"
                and (lease.scope != "input" or d.policy == "input")
                for d in inv.displays
            )
        else:
            source_allowed = any(
                c.camera_id == descriptor["source_id"] and c.available
                for c in inv.cameras
            )

        def reserve(doc: dict[str, Any]) -> dict[str, Any]:
            if doc.get("legacy_pending", {}).get("expires_at_ms", 0) > now_ms():
                reject("conflict")
            active = doc.get("stream")
            if doc.get("camera_stream", {}).get("state") in LIVE:
                reject("conflict")
            cap = doc.get("capability")
            binding = dict(cap["binding"]) if cap else None
            if binding and view.session_id is not None:
                binding["interactive_session_id"] = view.session_id
            context = {
                "authorized": True,
                "tenant_matches": True,
                "source_allowed": source_allowed,
                "sn": lease.sn,
                "lease_active": lease.is_active(),
                "lease_id": str(lease.lease_id),
                "now_ms": now_ms(),
                "active_start": (
                    active["start"] if active and active["state"] in LIVE else None
                ),
                "negotiated_v2": bool(
                    cap
                    and view.online
                    and doc.get("server_epoch") == server_epoch
                    and "video_contract_v2" in (view.capabilities or [])
                ),
                "capabilities": cap,
                "agent_instance_id": cap["agent_instance_id"] if cap else None,
                "binding": binding,
                "server_hevc_ready": settings.remote_input.video_hevc_chain_ready
                or test_camera,
                "test_camera_source": test_camera,
            }
            result = select_codec(start, context)
            if result == "already_running":
                assert active is not None
                return {**active, "result": "already_running"}
            if result not in ("h264", "h265"):
                reject(
                    result,
                    {"unsupported": 422, "forbidden": 403, "expired": 410}.get(
                        result, 409
                    ),
                )
            if result != start["resolved_codec"]:
                reject("codec_mismatch")
            if lease.stream_instance_id is not None:
                reject("conflict")
            if active and (
                active["start"]["stream_instance_id"] == start["stream_instance_id"]
                or active["start"]["operation_id"] == start["operation_id"]
            ):
                reject("conflict")
            state = {
                "version": 2,
                "start": start,
                "state": "starting",
                "error": None,
                "owner_user_id": lease.owner_user_id,
                "owner_session_id": lease.owner_session_id,
                "org_id": lease.org_id,
                "result": "accepted",
            }
            doc["stream"] = state
            return state

        async def guard(pipe: Any, doc: dict[str, Any]) -> None:
            current = await self.publisher_lease(service, start, pipe)
            if (
                current is None
                or command.lease_expires_at_ms
                > int(current.expires_at.timestamp() * 1000)
                or current.org_id != lease.org_id
                or current.owner_user_id != lease.owner_user_id
                or current.owner_session_id != lease.owner_session_id
                or current.scope not in ("input", "stream")
            ):
                reject("lease_invalid")

        state = await self.store.change(
            lease.sn,
            reserve,
            claim=(command.stream_instance_id, command.operation_id),
            expected_epoch=server_epoch,
            guard=guard,
        )
        if state["result"] == "already_running":
            return state
        lease.stream_contract_version = 2
        lease.stream_instance_id = UUID(command.stream_instance_id)
        lease.stream_mode = descriptor["source_type"]
        lease.stream_profile = descriptor["profile_id"]
        lease.stream_state = "starting"
        lease.selected_desktop_id = (
            descriptor["source_id"] if descriptor["source_type"] == "desktop" else None
        )
        lease.selected_camera_id = (
            descriptor["source_id"] if descriptor["source_type"] != "desktop" else None
        )
        if not await service.leases.save_stream(lease, None):
            await self.finish(
                lease.sn, command.stream_instance_id, "failed", "lease_invalid"
            )
            reject("lease_invalid")
        try:
            await asyncio.wait_for(
                send(lease.sn, command, ttl_ms=command.expires_at_ms - now_ms()),
                timeout=max(0.001, (command.expires_at_ms - now_ms()) / 1000),
            )
            while now_ms() < command.expires_at_ms:
                current = (await self.store.get(lease.sn)).get("stream", {})
                if (
                    current.get("start", {}).get("stream_instance_id")
                    != command.stream_instance_id
                ):
                    reject("conflict")
                if current.get("state") != "starting":
                    if current["state"] not in LIVE:
                        await self.clear_lease(service, lease.sn, current)
                        if current["state"] == "stopped":
                            # Revoke may have published STOP while START was in flight.
                            # Compensate only this epoch after START publication finishes.
                            try:
                                await self.stop_command(current, send)
                            except Exception:
                                log.warning(
                                    "V2 compensation STOP failed", exc_info=True
                                )
                    return current
                await asyncio.sleep(0.05)
            await self.terminate(service, state, "start_timeout", send)
            reject("producer_lost", 502)
        except HTTPException:
            raise
        except asyncio.CancelledError:
            await asyncio.shield(
                self.terminate(service, state, "caller_cancelled", send)
            )
            raise
        except Exception:
            await self.terminate(service, state, "publish_failed", send)
            raise

    async def clear_lease(self, service: Any, sn: str, state: dict[str, Any]) -> None:
        lease = await self.get_lease(service, UUID(state["start"]["lease_id"]))
        stream_id = UUID(state["start"]["stream_instance_id"])
        if lease and lease.stream_instance_id == stream_id:
            lease.stream_instance_id = None
            lease.stream_state = "stopped"
            await service.leases.save_stream(lease, stream_id)

    async def notify(
        self,
        service: Any,
        sn: str,
        stream_id: str,
        state: StreamState,
        reason: str | None,
    ) -> None:
        await service.presence.notify_video_event(
            CtlStreamEvent(
                sn=sn,
                stream_instance_id=UUID(stream_id),
                state=state,
                reason=reason,
                timestamp=datetime.now(UTC).isoformat(),
            )
        )

    async def terminate(
        self,
        service: Any,
        state: dict[str, Any],
        reason: str,
        send: Any,
        error: dict[str, Any] | None = None,
    ) -> None:
        start = state["start"]
        if not await self.finish(
            start["sn"], start["stream_instance_id"], "failed", reason, error
        ):
            return
        await self.clear_lease(service, start["sn"], state)
        await self.notify(
            service, start["sn"], start["stream_instance_id"], "failed", reason
        )
        try:
            await self.stop_command(state, send)
        except Exception:
            # The immutable deadline remains the producer's final watchdog.
            log.warning(
                "V2 STOP publication failed for stream=%s",
                start["stream_instance_id"],
                exc_info=True,
            )

    async def finish(
        self,
        sn: str,
        stream_id: str,
        state: str,
        reason: str,
        error: dict[str, Any] | None = None,
    ) -> bool:
        def update(doc: dict[str, Any]) -> bool:
            current = doc.get("stream")
            if (
                not current
                or current["start"]["stream_instance_id"] != stream_id
                or current["state"] not in LIVE
            ):
                return False
            if state == "failed" and error is None:
                error_code = (
                    "codec_mismatch"
                    if reason == "descriptor_mismatch"
                    else "producer_lost"
                )
                detail = {
                    "domain": "producer",
                    "code": error_code,
                    "scope": "stream",
                    "codec": current["start"]["resolved_codec"],
                    "backend": "unknown",
                    "stage": "unknown",
                    "current_stream_terminated": True,
                    "recovery_class": "unknown",
                    "suggested_action": "none",
                    "auto_restart_allowed": False,
                    "attempt": 0,
                }
            else:
                detail = error
            current.update(state=state, reason=reason, error=detail, result=state)
            if state == "failed" and current["start"]["resolved_codec"] == "h265":
                cap = doc.get("capability")
                if (
                    cap
                    and cap["agent_instance_id"]
                    == current["start"]["agent_instance_id"]
                ):
                    for entry in cap["video"]:
                        if entry["codec"] == "h265":
                            entry.update(
                                status="temporarily_unavailable",
                                reason_code=(detail or {}).get("code", "unknown"),
                                profiles=[],
                            )
            return True

        return await self.store.change(sn, update)

    async def event(self, sn: str, event: Any, service: Any, send: Any) -> bool:
        payload = event.model_dump(mode="json")
        state = (await self.store.get(sn)).get("stream")
        if not state or state["state"] not in LIVE or event.sn != sn:
            return False
        start = state["start"]
        if any(
            payload[k] != start[k]
            for k in ("lease_id", "stream_instance_id", "agent_instance_id")
        ):
            return False
        lease = await self.get_lease(service, UUID(start["lease_id"]))
        if isinstance(event, wire.Ready) and (
            not lease
            or not lease.is_active()
            or lease.stream_contract_version != 2
            or str(lease.stream_instance_id) != start["stream_instance_id"]
        ):
            return False
        if isinstance(event, wire.Ready):
            if now_ms() >= start["expires_at_ms"]:
                return False
            if (
                payload["command_id"] != start["command_id"]
                or payload["operation_id"] != start["operation_id"]
            ):
                return False
            if payload["actual_descriptor"] != start["descriptor"]:
                await self.terminate(service, state, "descriptor_mismatch", send)
                return True
            else:

                def ready(doc: dict[str, Any]) -> bool:
                    current = doc.get("stream", {})
                    candidate = current.get("start", {})
                    if (
                        current.get("state") != "starting"
                        or candidate.get("command_id") != start["command_id"]
                        or any(candidate.get(k) != start[k] for k in IDENTITY)
                    ):
                        return False
                    current.update(
                        state="running",
                        result="started",
                        actual_descriptor=payload["actual_descriptor"],
                    )
                    return True

                async def guard(pipe: Any, doc: dict[str, Any]) -> None:
                    if await self.publisher_lease(service, start, pipe) is None:
                        reject("lease_invalid")

                try:
                    accepted = await self.store.change(sn, ready, guard=guard)
                except HTTPException as exc:
                    if exc.detail == {"code": "lease_invalid"}:
                        return False
                    raise
                if not accepted:
                    return False
        else:
            if (
                payload["descriptor_revision"]
                != start["descriptor"]["descriptor_revision"]
            ):
                return False
            if not await self.finish(
                sn,
                event.stream_instance_id,
                "failed",
                payload["reason"],
                payload["error"],
            ):
                return False
        current = (await self.store.get(sn))["stream"]
        if current["start"]["stream_instance_id"] != event.stream_instance_id:
            return False
        if lease and str(lease.stream_instance_id) == event.stream_instance_id:
            previous_stream = lease.stream_instance_id
            lease.stream_state = current["state"]
            if current["state"] not in LIVE:
                lease.stream_instance_id = None
            await service.leases.save_stream(lease, previous_stream)
        await service.presence.notify_video_event(
            CtlStreamEvent(
                sn=sn,
                stream_instance_id=UUID(event.stream_instance_id),
                state=current["state"],
                reason=current.get("reason"),
                timestamp=datetime.now(UTC).isoformat(),
            )
        )
        return True

    async def command_reply(self, sn: str, event: Any, service: Any, send: Any) -> bool:
        state = (await self.store.get(sn)).get("stream")
        if not state or state["state"] != "starting":
            return False
        start = state["start"]
        if event.command_id != start["command_id"]:
            return False
        if isinstance(event, wire.StartAck):
            return (
                event.lease_id == start["lease_id"]
                and event.stream_instance_id == start["stream_instance_id"]
                and event.descriptor_revision
                == start["descriptor"]["descriptor_revision"]
            )
        await self.terminate(service, state, event.code.value, send)
        return True

    async def stop_command(self, state: dict[str, Any], send: Any) -> None:
        start = state["start"]
        current = now_ms()
        command = wire.Stop(
            v=2,
            type="stream_stop",
            command_id=str(uuid4()),
            sn=start["sn"],
            lease_id=start["lease_id"],
            stream_instance_id=start["stream_instance_id"],
            agent_instance_id=start["agent_instance_id"],
            descriptor_revision=start["descriptor"]["descriptor_revision"],
            issued_at_ms=current,
            expires_at_ms=current + 5000,
        )
        await asyncio.wait_for(send(start["sn"], command, ttl_ms=5000), timeout=5.0)

    async def stop_for_lease(
        self, lease: Any, send: Any, reason: str = "released", presence: Any = None
    ) -> bool:
        if lease.stream_contract_version != 2:
            return False
        document = await self.store.get(lease.sn)
        camera_record = document.get("camera_stream")
        if camera_record and camera_record["start"]["lease_id"] == str(lease.lease_id):
            from core.camera.control import camera_control, epoch_of

            epoch = epoch_of(camera_record)
            if (
                lease.stream_instance_id is not None
                and str(lease.stream_instance_id)
                != epoch.identity["stream_instance_id"]
            ):
                return False
            await camera_control.stop(
                None, lease, {**epoch.identity, "reason": reason}, send
            )
            return True
        state = document.get("stream")
        if not state or state["start"]["lease_id"] != str(lease.lease_id):
            return False
        if (
            lease.stream_instance_id is not None
            and str(lease.stream_instance_id) != state["start"]["stream_instance_id"]
        ):
            return False
        if state["state"] in LIVE:
            changed = await self.finish(
                lease.sn, state["start"]["stream_instance_id"], "stopped", reason
            )
            if not changed:
                return True
            if presence is None:
                from core.remote_input.presence import presence_registry

                presence = presence_registry
            await presence.notify_video_event(
                CtlStreamEvent(
                    sn=lease.sn,
                    stream_instance_id=UUID(state["start"]["stream_instance_id"]),
                    state="stopped",
                    reason=reason,
                    timestamp=datetime.now(UTC).isoformat(),
                )
            )
            try:
                await self.stop_command(state, send)
            except Exception:
                log.warning(
                    "V2 STOP failed during %s for stream=%s",
                    reason,
                    state["start"]["stream_instance_id"],
                    exc_info=True,
                )
        return True

    async def stop(
        self,
        service: Any,
        command: wire.Stop,
        org_id: int,
        user: str,
        session: str,
        send: Any,
        superuser: bool = False,
    ) -> dict[str, Any]:
        lease = await self.authorize(
            service, UUID(command.lease_id), org_id, user, session, superuser
        )
        state = (await self.store.get(lease.sn)).get("stream")
        if not state or command.sn != lease.sn:
            reject("lease_mismatch")
        start = state["start"]
        if (
            any(
                getattr(command, k) != start[k]
                for k in ("lease_id", "stream_instance_id", "agent_instance_id")
            )
            or command.descriptor_revision != start["descriptor"]["descriptor_revision"]
        ):
            reject("conflict")
        if not 0 < command.expires_at_ms - command.issued_at_ms <= 30000:
            reject("invalid_payload", 400)
        if not command.issued_at_ms <= now_ms() < command.expires_at_ms:
            reject("expired", 410)
        await self.stop_for_lease(lease, send, "user_requested", service.presence)
        await self.clear_lease(service, lease.sn, state)
        current = (await self.store.get(lease.sn))["stream"]
        return current


video_control = VideoControl()
