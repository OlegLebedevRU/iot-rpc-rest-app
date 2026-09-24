from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    TimeoutError as RedisTimeoutError,
    WatchError,
)

from core.config import settings
from core.logging_config import setup_module_logger
from core.redis_helper import redis_helper
from core.remote_input.publisher import send_ctl_command
from core.remote_input.schemas import LeaseScope, StreamStopCommand

log = setup_module_logger(__name__, "remote_input.log")


def mask_user_id(user_id: str) -> str:
    if not user_id:
        return "***"
    if len(user_id) <= 4:
        return user_id[0] + "***" if len(user_id) > 1 else "***"
    return f"{user_id[:2]}***{user_id[-2:]}"


@dataclass(slots=True)
class Lease:
    lease_id: UUID
    org_id: int
    device_id: int
    sn: str
    owner_user_id: str
    owner_role: str
    scope: LeaseScope = "input"
    owner_session_id: str = ""
    selected_desktop_id: str | None = None
    selected_session_id: int | None = None
    stream_instance_id: UUID | None = None
    stream_mode: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_keepalive_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    revoked_reason: str | None = None
    ws_connected: bool = False
    ws_disconnected_at: datetime | None = None
    listeners: list[asyncio.Queue[str]] = field(default_factory=list)
    selected_camera_id: str | None = None
    ttl_sec: int = 60
    stream_state: str | None = None

    @property
    def issued_at(self) -> datetime:
        return self.created_at

    @property
    def heartbeat_at(self) -> datetime:
        return self.last_keepalive_at

    def is_active(self, now: datetime | None = None) -> bool:
        if self.revoked_reason is not None:
            return False
        return (now or datetime.now(UTC)) < self.expires_at

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(UTC)) >= self.expires_at


class LeaseConflictError(Exception):
    def __init__(self, active_lease: Lease) -> None:
        self.active_lease = active_lease
        self.code = "lease_taken"
        self.owner_role = active_lease.owner_role
        self.owner_user_id_masked = mask_user_id(active_lease.owner_user_id)
        self.scope = active_lease.scope
        self.expires_at = active_lease.expires_at.isoformat()
        super().__init__(
            f"Lease busy on sn={active_lease.sn} by owner={active_lease.owner_user_id} (masked: {self.owner_user_id_masked}) scope={self.scope} expires_at={self.expires_at}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "owner_role": self.owner_role,
            "owner_user_id_masked": self.owner_user_id_masked,
            "scope": self.scope,
            "expires_at": self.expires_at,
        }


class LeaseRegistryProtocol(Protocol):
    async def acquire(
        self,
        org_id: int,
        device_id: int,
        sn: str,
        owner_user_id: str,
        owner_role: str,
        ttl_sec: int,
        scope: LeaseScope = "input",
        owner_session_id: str = "",
    ) -> Lease: ...

    async def touch(self, lease_id: UUID, ttl_sec: int) -> Lease | None: ...

    async def upgrade_scope(
        self, lease_id: UUID, new_scope: LeaseScope
    ) -> Lease | None: ...

    async def revoke(
        self, lease_id: UUID, reason: str = "released"
    ) -> Lease | None: ...

    async def revoke_by_owner(
        self,
        owner_user_id: str,
        owner_session_id: str | None = None,
        reason: str = "owner_logout",
    ) -> list[Lease]: ...

    async def get(self, lease_id: UUID) -> Lease | None: ...

    async def get_active(self, sn: str) -> Lease | None: ...

    async def get_active_by_sn(self, sn: str) -> Lease | None: ...

    async def cleanup_expired(self) -> list[tuple[Lease, str]]: ...

    async def subscribe_revocation(
        self, lease_id: UUID
    ) -> asyncio.Queue[str] | None: ...

    async def unsubscribe_revocation(
        self, lease_id: UUID, queue: asyncio.Queue[str]
    ) -> None: ...

    async def mark_ws_connected(self, lease_id: UUID) -> bool: ...

    async def mark_ws_disconnected(self, lease_id: UUID) -> None: ...


class LeaseRegistry:
    def __init__(self) -> None:
        self._leases_by_id: dict[UUID, Lease] = {}
        self._active_by_sn: dict[str, UUID] = {}
        self._active_ws_leases: set[UUID] = set()
        self._lock = asyncio.Lock()

    async def acquire(
        self,
        org_id: int,
        device_id: int,
        sn: str,
        owner_user_id: str,
        owner_role: str,
        ttl_sec: int,
        scope: LeaseScope = "input",
        owner_session_id: str = "",
    ) -> Lease:
        now = datetime.now(UTC)
        async with self._lock:
            existing_id = self._active_by_sn.get(sn)
            if existing_id is not None:
                existing = self._leases_by_id.get(existing_id)
                if existing is not None and existing.is_active(now):
                    same_user = existing.owner_user_id == owner_user_id
                    same_session = existing.owner_session_id == owner_session_id
                    if same_user and same_session:
                        # Idempotent re-acquire
                        existing.ttl_sec = ttl_sec
                        if existing.scope == scope:
                            existing.last_keepalive_at = now
                            existing.expires_at = now + timedelta(seconds=ttl_sec)
                            if existing.stream_mode is None and scope in (
                                "stream",
                                "input",
                            ):
                                existing.stream_mode = "desktop"
                            return existing
                        else:
                            # Upgrade scope
                            existing.scope = scope
                            existing.last_keepalive_at = now
                            existing.expires_at = now + timedelta(seconds=ttl_sec)
                            if existing.stream_mode is None and scope in (
                                "stream",
                                "input",
                            ):
                                existing.stream_mode = "desktop"
                            return existing
                    else:
                        raise LeaseConflictError(existing)
                # If expired/revoked, remove stale mapping
                self._active_by_sn.pop(sn, None)

            lease_id = uuid4()
            expires_at = now + timedelta(seconds=ttl_sec)
            stream_mode = "desktop" if scope in ("stream", "input") else None
            lease = Lease(
                lease_id=lease_id,
                org_id=org_id,
                device_id=device_id,
                sn=sn,
                owner_user_id=owner_user_id,
                owner_role=owner_role,
                scope=scope,
                owner_session_id=owner_session_id,
                stream_mode=stream_mode,
                created_at=now,
                expires_at=expires_at,
                last_keepalive_at=now,
                ttl_sec=ttl_sec,
            )
            self._leases_by_id[lease_id] = lease
            self._active_by_sn[sn] = lease_id

        log.info(
            "Lease acquired: lease_id=%s sn=%s device_id=%s org_id=%s owner=%s scope=%s expires_at=%s",
            lease.lease_id,
            sn,
            device_id,
            org_id,
            owner_user_id,
            scope,
            lease.expires_at.isoformat(),
        )
        return lease

    async def touch(self, lease_id: UUID, ttl_sec: int) -> Lease | None:
        now = datetime.now(UTC)
        async with self._lock:
            lease = self._leases_by_id.get(lease_id)
            if lease is None or not lease.is_active(now):
                return None
            lease.last_keepalive_at = now
            lease.expires_at = now + timedelta(seconds=ttl_sec)
            lease.ttl_sec = ttl_sec
            return lease

    async def upgrade_scope(
        self, lease_id: UUID, new_scope: LeaseScope
    ) -> Lease | None:
        now = datetime.now(UTC)
        async with self._lock:
            lease = self._leases_by_id.get(lease_id)
            if lease is None or not lease.is_active(now):
                return None
            lease.scope = new_scope
            if lease.stream_mode is None and new_scope in ("stream", "input"):
                lease.stream_mode = "desktop"
            return lease

    async def revoke(self, lease_id: UUID, reason: str = "released") -> Lease | None:
        async with self._lock:
            lease = self._leases_by_id.get(lease_id)
            if lease is None:
                return None
            if lease.revoked_reason is not None:
                return lease
            lease.revoked_reason = reason
            if self._active_by_sn.get(lease.sn) == lease_id:
                self._active_by_sn.pop(lease.sn, None)
            self._active_ws_leases.discard(lease_id)
            listeners = list(lease.listeners)

        for q in listeners:
            try:
                q.put_nowait(reason)
            except Exception:
                pass

        # Side effects for revoked lease
        if lease.scope in ("stream", "input") and lease.stream_instance_id is not None:
            try:
                now_ms = int(time.time() * 1000)
                stop_cmd = StreamStopCommand(
                    command_id=uuid4(),
                    lease_id=lease.lease_id,
                    sn=lease.sn,
                    stream_instance_id=lease.stream_instance_id,
                    issued_at_ms=now_ms,
                    expires_at_ms=now_ms + 5000,
                )
                await send_ctl_command(lease.sn, stop_cmd, ttl_ms=5000)
                log.info(
                    "Sent stream_stop on revoke: lease_id=%s sn=%s instance=%s",
                    lease.lease_id,
                    lease.sn,
                    lease.stream_instance_id,
                )
            except Exception as exc:
                log.warning("Failed to publish stream_stop on lease revoke: %s", exc)

        if lease.scope == "console":
            try:
                from core.diagnostics.sessions import diagnostics_session_registry

                diag_sessions = await diagnostics_session_registry.remove_all_for_sn(
                    lease.sn
                )
                for sess in diag_sessions:
                    if getattr(sess, "ws", None) is not None:
                        try:
                            await sess.ws.close(
                                code=4409, reason=f"lease_revoked:{reason}"
                            )
                        except Exception:
                            pass
                log.info(
                    "Closed %d diagnostics session(s) on console lease revoke for sn=%s",
                    len(diag_sessions),
                    lease.sn,
                )
            except Exception as exc:
                log.warning(
                    "Failed to remove diagnostics sessions on console revoke: %s", exc
                )

        log.info(
            "Lease revoked: lease_id=%s sn=%s scope=%s reason=%s",
            lease_id,
            lease.sn,
            lease.scope,
            reason,
        )
        return lease

    async def revoke_by_owner(
        self,
        owner_user_id: str,
        owner_session_id: str | None = None,
        reason: str = "owner_logout",
    ) -> list[Lease]:
        leases_to_revoke: list[UUID] = []
        async with self._lock:
            for lease_id in list(self._active_by_sn.values()):
                lease_item = self._leases_by_id.get(lease_id)
                if lease_item and lease_item.is_active():
                    if lease_item.owner_user_id == owner_user_id:
                        if (
                            owner_session_id is None
                            or lease_item.owner_session_id == owner_session_id
                        ):
                            leases_to_revoke.append(lease_id)

        revoked: list[Lease] = []
        for lid in leases_to_revoke:
            rev_l = await self.revoke(lid, reason=reason)
            if rev_l:
                revoked.append(rev_l)
        return revoked

    async def get(self, lease_id: UUID) -> Lease | None:
        async with self._lock:
            return self._leases_by_id.get(lease_id)

    async def get_active(self, sn: str) -> Lease | None:
        now = datetime.now(UTC)
        async with self._lock:
            lease_id = self._active_by_sn.get(sn)
            if lease_id is None:
                return None
            lease = self._leases_by_id.get(lease_id)
            if lease is None or not lease.is_active(now):
                return None
            return lease

    async def get_active_by_sn(self, sn: str) -> Lease | None:
        return await self.get_active(sn)

    async def cleanup_expired(self) -> list[tuple[Lease, str]]:
        now = datetime.now(UTC)
        grace_sec = settings.remote_input.ws_disconnect_grace_sec
        expired_ids: list[tuple[UUID, str]] = []

        async with self._lock:
            for sn, lease_id in list(self._active_by_sn.items()):
                lease = self._leases_by_id.get(lease_id)
                if lease is None:
                    self._active_by_sn.pop(sn, None)
                    continue

                if lease.is_expired(now):
                    expired_ids.append((lease_id, "expired"))
                elif (
                    lease.ws_disconnected_at is not None
                    and not lease.ws_connected
                    and (now - lease.ws_disconnected_at).total_seconds() >= grace_sec
                ):
                    expired_ids.append((lease_id, "ws_disconnect_timeout"))

        expired: list[tuple[Lease, str]] = []
        for lid, reason in expired_ids:
            revoked_lease = await self.revoke(lid, reason=reason)
            if revoked_lease:
                expired.append((revoked_lease, reason))

        return expired

    async def subscribe_revocation(self, lease_id: UUID) -> asyncio.Queue[str] | None:
        async with self._lock:
            lease = self._leases_by_id.get(lease_id)
            if lease is None:
                return None
            q: asyncio.Queue[str] = asyncio.Queue()
            lease.listeners.append(q)
            return q

    async def unsubscribe_revocation(
        self, lease_id: UUID, queue: asyncio.Queue[str]
    ) -> None:
        async with self._lock:
            lease = self._leases_by_id.get(lease_id)
            if lease is not None and queue in lease.listeners:
                lease.listeners.remove(queue)

    async def mark_ws_connected(self, lease_id: UUID) -> bool:
        async with self._lock:
            if lease_id in self._active_ws_leases:
                return False
            lease = self._leases_by_id.get(lease_id)
            if lease is None:
                return False
            lease.ws_connected = True
            lease.ws_disconnected_at = None
            self._active_ws_leases.add(lease_id)
            return True

    async def mark_ws_disconnected(self, lease_id: UUID) -> None:
        now = datetime.now(UTC)
        async with self._lock:
            lease = self._leases_by_id.get(lease_id)
            if lease is not None:
                lease.ws_connected = False
                lease.ws_disconnected_at = now
            self._active_ws_leases.discard(lease_id)


def _lease_to_dict(lease: Lease) -> dict[str, str]:
    return {
        "lease_id": str(lease.lease_id),
        "org_id": str(lease.org_id),
        "device_id": str(lease.device_id),
        "sn": lease.sn,
        "owner_user_id": lease.owner_user_id,
        "owner_role": lease.owner_role,
        "scope": str(lease.scope),
        "owner_session_id": lease.owner_session_id or "",
        "selected_desktop_id": lease.selected_desktop_id or "",
        "selected_session_id": (
            str(lease.selected_session_id)
            if lease.selected_session_id is not None
            else ""
        ),
        "stream_instance_id": (
            str(lease.stream_instance_id)
            if lease.stream_instance_id is not None
            else ""
        ),
        "stream_mode": lease.stream_mode or "",
        "created_at": lease.created_at.isoformat(),
        "expires_at": lease.expires_at.isoformat(),
        "last_keepalive_at": lease.last_keepalive_at.isoformat(),
        "revoked_reason": lease.revoked_reason or "",
        "ws_connected": "1" if lease.ws_connected else "0",
        "ws_disconnected_at": (
            lease.ws_disconnected_at.isoformat() if lease.ws_disconnected_at else ""
        ),
        "selected_camera_id": lease.selected_camera_id or "",
        "ttl_sec": str(lease.ttl_sec),
        "stream_state": lease.stream_state or "",
    }


def _dict_to_lease(
    d: dict[str, str], listeners: list[asyncio.Queue[str]] | None = None
) -> Lease:
    return Lease(
        lease_id=UUID(d["lease_id"]),
        org_id=int(d["org_id"]),
        device_id=int(d["device_id"]),
        sn=d["sn"],
        owner_user_id=d["owner_user_id"],
        owner_role=d["owner_role"],
        scope=d.get("scope", "input"),  # type: ignore
        owner_session_id=d.get("owner_session_id", ""),
        selected_desktop_id=d.get("selected_desktop_id") or None,
        selected_session_id=(
            int(d["selected_session_id"]) if d.get("selected_session_id") else None
        ),
        stream_instance_id=(
            UUID(d["stream_instance_id"]) if d.get("stream_instance_id") else None
        ),
        stream_mode=d.get("stream_mode") or None,
        created_at=datetime.fromisoformat(d["created_at"]),
        expires_at=datetime.fromisoformat(d["expires_at"]),
        last_keepalive_at=datetime.fromisoformat(d["last_keepalive_at"]),
        revoked_reason=d.get("revoked_reason") or None,
        ws_connected=d.get("ws_connected") == "1",
        ws_disconnected_at=(
            datetime.fromisoformat(d["ws_disconnected_at"])
            if d.get("ws_disconnected_at")
            else None
        ),
        listeners=listeners if listeners is not None else [],
        selected_camera_id=d.get("selected_camera_id") or None,
        ttl_sec=int(d.get("ttl_sec", 60)),
        stream_state=d.get("stream_state") or None,
    )


class _CompatibilityLeasesDict(dict):
    def __init__(self, registry: RedisLeaseRegistry) -> None:
        super().__init__()
        self._registry = registry

    def clear(self) -> None:
        super().clear()
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._registry._delete_all_redis_keys())
        except RuntimeError:
            pass


class _CompatibilityActiveSnDict(dict):
    def __init__(self, registry: RedisLeaseRegistry) -> None:
        super().__init__()
        self._registry = registry

    def clear(self) -> None:
        super().clear()
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._registry._delete_all_redis_keys())
        except RuntimeError:
            pass


class RedisLeaseRegistry:
    def __init__(self) -> None:
        self._leases_by_id: dict[UUID, Lease] = _CompatibilityLeasesDict(self)
        self._active_by_sn: dict[str, UUID] = _CompatibilityActiveSnDict(self)
        self._active_ws_leases: set[UUID] = set()
        self._listeners: dict[UUID, list[asyncio.Queue[str]]] = {}
        self._lock = asyncio.Lock()
        self._pubsub_task: asyncio.Task | None = None

    @property
    def _client(self):
        return redis_helper.get_client()

    async def _delete_all_redis_keys(self) -> None:
        try:
            client = self._client
            keys = await client.keys("l4d:lease:*")
            if keys:
                await client.delete(*keys)
        except Exception as exc:
            log.debug("Failed deleting all lease redis keys: %s", exc)

    async def _ensure_pubsub_listener(self) -> None:
        if self._pubsub_task is not None and not self._pubsub_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
            self._pubsub_task = loop.create_task(self._pubsub_worker())
        except RuntimeError:
            pass

    async def _pubsub_worker(self) -> None:
        client = self._client
        pubsub = client.pubsub()
        try:
            await pubsub.subscribe("l4d:pubsub:lease_revoked")
            while True:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if msg and msg.get("type") == "message":
                    raw_data = msg.get("data")
                    if raw_data:
                        try:
                            data = json.loads(raw_data)
                            lid_str = data.get("lease_id")
                            reason = data.get("reason", "released")
                            if lid_str:
                                lid = UUID(lid_str)
                                queues = list(self._listeners.get(lid, []))
                                for q in queues:
                                    try:
                                        q.put_nowait(reason)
                                    except Exception:
                                        pass
                        except Exception as exc:
                            log.debug("Error parsing lease_revoked pubsub: %s", exc)
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            try:
                await pubsub.unsubscribe("l4d:pubsub:lease_revoked")
                await pubsub.aclose()
            except Exception:
                pass
        except Exception as exc:
            log.warning("Lease pubsub worker stopped: %s", exc)

    async def acquire(
        self,
        org_id: int,
        device_id: int,
        sn: str,
        owner_user_id: str,
        owner_role: str,
        ttl_sec: int,
        scope: LeaseScope = "input",
        owner_session_id: str = "",
    ) -> Lease:
        now = datetime.now(UTC)
        active_key = f"l4d:lease:active:{sn}"
        client = self._client

        for attempt in range(5):
            try:
                async with client.pipeline(transaction=True) as pipe:
                    await pipe.watch(active_key)
                    existing_id_str = await client.get(active_key)
                    if existing_id_str is not None:
                        existing_hash_key = f"l4d:lease:{existing_id_str}"
                        raw_data = await client.hgetall(existing_hash_key)
                        if raw_data:
                            existing = _dict_to_lease(
                                raw_data,
                                self._listeners.get(UUID(existing_id_str), []),
                            )
                            if existing.is_active(now):
                                same_user = existing.owner_user_id == owner_user_id
                                same_session = (
                                    existing.owner_session_id == owner_session_id
                                )
                                if same_user and same_session:
                                    existing.ttl_sec = ttl_sec
                                    existing.last_keepalive_at = now
                                    existing.expires_at = now + timedelta(
                                        seconds=ttl_sec
                                    )
                                    if existing.scope != scope:
                                        existing.scope = scope
                                    if existing.stream_mode is None and scope in (
                                        "stream",
                                        "input",
                                    ):
                                        existing.stream_mode = "desktop"

                                    pipe.multi()
                                    pipe.hset(
                                        existing_hash_key,
                                        mapping=_lease_to_dict(existing),
                                    )
                                    pipe.expire(existing_hash_key, ttl_sec + 30)
                                    pipe.expire(active_key, ttl_sec)
                                    await pipe.execute()

                                    async with self._lock:
                                        self._leases_by_id[existing.lease_id] = existing
                                        self._active_by_sn[sn] = existing.lease_id
                                    return existing
                                else:
                                    raise LeaseConflictError(existing)

                    lease_id = uuid4()
                    lease_hash_key = f"l4d:lease:{lease_id}"
                    expires_at = now + timedelta(seconds=ttl_sec)
                    stream_mode = "desktop" if scope in ("stream", "input") else None
                    lease = Lease(
                        lease_id=lease_id,
                        org_id=org_id,
                        device_id=device_id,
                        sn=sn,
                        owner_user_id=owner_user_id,
                        owner_role=owner_role,
                        scope=scope,
                        owner_session_id=owner_session_id,
                        stream_mode=stream_mode,
                        created_at=now,
                        expires_at=expires_at,
                        last_keepalive_at=now,
                        ttl_sec=ttl_sec,
                    )
                    pipe.multi()
                    pipe.set(active_key, str(lease_id), ex=ttl_sec)
                    pipe.hset(lease_hash_key, mapping=_lease_to_dict(lease))
                    pipe.expire(lease_hash_key, ttl_sec + 30)
                    await pipe.execute()

                    async with self._lock:
                        self._leases_by_id[lease_id] = lease
                        self._active_by_sn[sn] = lease_id

                    log.info(
                        "Lease acquired (redis): lease_id=%s sn=%s device_id=%s org_id=%s owner=%s scope=%s expires_at=%s",
                        lease.lease_id,
                        sn,
                        device_id,
                        org_id,
                        owner_user_id,
                        scope,
                        lease.expires_at.isoformat(),
                    )
                    return lease
            except WatchError:
                if attempt == 4:
                    raise
                continue
            except (RedisConnectionError, RedisTimeoutError) as exc:
                log.error(
                    "Redis connection error during lease acquire for sn=%s: %s",
                    sn,
                    exc,
                )
                raise

        raise RuntimeError("Failed to acquire lease due to concurrent retries")

    async def touch(self, lease_id: UUID, ttl_sec: int) -> Lease | None:
        now = datetime.now(UTC)
        lease_hash_key = f"l4d:lease:{lease_id}"
        client = self._client
        try:
            raw_data = await client.hgetall(lease_hash_key)
            if not raw_data:
                return None
            lease = _dict_to_lease(raw_data, self._listeners.get(lease_id, []))
            if not lease.is_active(now):
                return None
            lease.last_keepalive_at = now
            lease.expires_at = now + timedelta(seconds=ttl_sec)
            lease.ttl_sec = ttl_sec
            active_key = f"l4d:lease:active:{lease.sn}"

            async with client.pipeline(transaction=True) as pipe:
                pipe.hset(lease_hash_key, mapping=_lease_to_dict(lease))
                pipe.expire(lease_hash_key, ttl_sec + 30)
                cur_active = await client.get(active_key)
                if cur_active == str(lease_id):
                    pipe.expire(active_key, ttl_sec)
                await pipe.execute()

            async with self._lock:
                self._leases_by_id[lease_id] = lease
                self._active_by_sn[lease.sn] = lease_id
            return lease
        except (RedisConnectionError, RedisTimeoutError) as exc:
            log.error(
                "Redis connection error during touch for lease_id=%s: %s",
                lease_id,
                exc,
            )
            raise

    async def upgrade_scope(
        self, lease_id: UUID, new_scope: LeaseScope
    ) -> Lease | None:
        now = datetime.now(UTC)
        lease_hash_key = f"l4d:lease:{lease_id}"
        client = self._client
        try:
            raw_data = await client.hgetall(lease_hash_key)
            if not raw_data:
                return None
            lease = _dict_to_lease(raw_data, self._listeners.get(lease_id, []))
            if not lease.is_active(now):
                return None
            lease.scope = new_scope
            if lease.stream_mode is None and new_scope in ("stream", "input"):
                lease.stream_mode = "desktop"
            await client.hset(lease_hash_key, mapping=_lease_to_dict(lease))
            async with self._lock:
                self._leases_by_id[lease_id] = lease
            return lease
        except (RedisConnectionError, RedisTimeoutError) as exc:
            log.error(
                "Redis connection error during upgrade_scope for lease_id=%s: %s",
                lease_id,
                exc,
            )
            raise

    async def revoke(
        self,
        lease_id: UUID,
        reason: str = "released",
        owner_user_id: str | None = None,
    ) -> Lease | None:
        lease_hash_key = f"l4d:lease:{lease_id}"
        client = self._client
        try:
            raw_data = await client.hgetall(lease_hash_key)
            if not raw_data:
                return None
            listeners = list(self._listeners.get(lease_id, []))
            lease = _dict_to_lease(raw_data, listeners)
            if owner_user_id is not None and lease.owner_user_id != owner_user_id:
                log.warning(
                    "Revoke denied: owner mismatch for lease_id=%s expected=%s actual=%s",
                    lease_id,
                    owner_user_id,
                    lease.owner_user_id,
                )
                raise PermissionError(
                    f"Lease {lease_id} is owned by {lease.owner_user_id}, not {owner_user_id}"
                )
            if lease.revoked_reason is not None:
                return lease

            lease.revoked_reason = reason
            active_key = f"l4d:lease:active:{lease.sn}"

            async with client.pipeline(transaction=True) as pipe:
                pipe.hset(lease_hash_key, "revoked_reason", reason)
                pipe.expire(lease_hash_key, 60)
                cur_active = await client.get(active_key)
                if cur_active == str(lease_id):
                    pipe.delete(active_key)
                await pipe.execute()

            try:
                msg_payload = json.dumps(
                    {
                        "lease_id": str(lease_id),
                        "sn": lease.sn,
                        "reason": reason,
                    }
                )
                await client.publish("l4d:pubsub:lease_revoked", msg_payload)
            except Exception as pub_exc:
                log.warning(
                    "Failed to publish to l4d:pubsub:lease_revoked: %s", pub_exc
                )

            async with self._lock:
                self._leases_by_id[lease_id] = lease
                if self._active_by_sn.get(lease.sn) == lease_id:
                    self._active_by_sn.pop(lease.sn, None)
                self._active_ws_leases.discard(lease_id)

            for q in listeners:
                try:
                    q.put_nowait(reason)
                except Exception:
                    pass

            if (
                lease.scope
                in (
                    "stream",
                    "input",
                )
                and lease.stream_instance_id is not None
            ):
                try:
                    now_ms = int(time.time() * 1000)
                    stop_cmd = StreamStopCommand(
                        command_id=uuid4(),
                        lease_id=lease.lease_id,
                        sn=lease.sn,
                        stream_instance_id=lease.stream_instance_id,
                        issued_at_ms=now_ms,
                        expires_at_ms=now_ms + 5000,
                    )
                    await send_ctl_command(lease.sn, stop_cmd, ttl_ms=5000)
                    log.info(
                        "Sent stream_stop on revoke: lease_id=%s sn=%s instance=%s",
                        lease.lease_id,
                        lease.sn,
                        lease.stream_instance_id,
                    )
                except Exception as exc:
                    log.warning(
                        "Failed to publish stream_stop on lease revoke: %s", exc
                    )

            if lease.scope == "console":
                try:
                    from core.diagnostics.sessions import (
                        diagnostics_session_registry,
                    )

                    diag_sessions = (
                        await diagnostics_session_registry.remove_all_for_sn(lease.sn)
                    )
                    for sess in diag_sessions:
                        if getattr(sess, "ws", None) is not None:
                            try:
                                await sess.ws.close(
                                    code=4409, reason=f"lease_revoked:{reason}"
                                )
                            except Exception:
                                pass
                    log.info(
                        "Closed %d diagnostics session(s) on console lease revoke for sn=%s",
                        len(diag_sessions),
                        lease.sn,
                    )
                except Exception as exc:
                    log.warning(
                        "Failed to remove diagnostics sessions on console revoke: %s",
                        exc,
                    )

            log.info(
                "Lease revoked (redis): lease_id=%s sn=%s scope=%s reason=%s",
                lease_id,
                lease.sn,
                lease.scope,
                reason,
            )
            return lease
        except (RedisConnectionError, RedisTimeoutError) as exc:
            log.error(
                "Redis connection error during revoke for lease_id=%s: %s",
                lease_id,
                exc,
            )
            raise

    async def revoke_by_owner(
        self,
        owner_user_id: str,
        owner_session_id: str | None = None,
        reason: str = "owner_logout",
    ) -> list[Lease]:
        client = self._client
        leases_to_revoke: list[UUID] = []
        try:
            active_keys = await client.keys("l4d:lease:active:*")
            for akey in active_keys:
                active_id_str = await client.get(akey)
                if not active_id_str:
                    continue
                lease_item = await self.get(UUID(active_id_str))
                if lease_item and lease_item.is_active():
                    if lease_item.owner_user_id == owner_user_id:
                        if (
                            owner_session_id is None
                            or lease_item.owner_session_id == owner_session_id
                        ):
                            leases_to_revoke.append(lease_item.lease_id)
        except (RedisConnectionError, RedisTimeoutError) as exc:
            log.error("Redis connection error in revoke_by_owner: %s", exc)
            raise

        revoked: list[Lease] = []
        for lid in leases_to_revoke:
            rev_l = await self.revoke(lid, reason=reason)
            if rev_l:
                revoked.append(rev_l)
        return revoked

    async def get(self, lease_id: UUID) -> Lease | None:
        async with self._lock:
            local = self._leases_by_id.get(lease_id)
            if local is not None:
                try:
                    client = self._client
                    await client.hset(
                        f"l4d:lease:{lease_id}",
                        mapping=_lease_to_dict(local),
                    )
                except Exception:
                    pass
                return local

        lease_hash_key = f"l4d:lease:{lease_id}"
        client = self._client
        try:
            raw_data = await client.hgetall(lease_hash_key)
            if not raw_data:
                return None
            lease = _dict_to_lease(raw_data, self._listeners.get(lease_id, []))
            async with self._lock:
                self._leases_by_id[lease_id] = lease
            return lease
        except (RedisConnectionError, RedisTimeoutError) as exc:
            log.error(
                "Redis connection error during get for lease_id=%s: %s",
                lease_id,
                exc,
            )
            raise

    async def get_active(self, sn: str) -> Lease | None:
        now = datetime.now(UTC)
        active_key = f"l4d:lease:active:{sn}"
        client = self._client
        try:
            active_id = await client.get(active_key)
            if not active_id:
                return None
            lease = await self.get(UUID(active_id))
            if lease is None or not lease.is_active(now):
                return None
            return lease
        except (RedisConnectionError, RedisTimeoutError) as exc:
            log.error(
                "Redis connection error during get_active for sn=%s: %s",
                sn,
                exc,
            )
            raise

    async def get_active_by_sn(self, sn: str) -> Lease | None:
        return await self.get_active(sn)

    async def cleanup_expired(self) -> list[tuple[Lease, str]]:
        now = datetime.now(UTC)
        grace_sec = settings.remote_input.ws_disconnect_grace_sec
        client = self._client
        expired: list[tuple[Lease, str]] = []

        try:
            active_keys = await client.keys("l4d:lease:active:*")
            for akey in active_keys:
                active_id_str = await client.get(akey)
                if not active_id_str:
                    continue
                lease = await self.get(UUID(active_id_str))
                if lease is None:
                    await client.delete(akey)
                    continue

                if lease.is_expired(now):
                    revoked_lease = await self.revoke(lease.lease_id, reason="expired")
                    if revoked_lease:
                        expired.append((revoked_lease, "expired"))
                elif (
                    lease.ws_disconnected_at is not None
                    and not lease.ws_connected
                    and (now - lease.ws_disconnected_at).total_seconds() >= grace_sec
                ):
                    revoked_lease = await self.revoke(
                        lease.lease_id, reason="ws_disconnect_timeout"
                    )
                    if revoked_lease:
                        expired.append((revoked_lease, "ws_disconnect_timeout"))
            return expired
        except (RedisConnectionError, RedisTimeoutError) as exc:
            log.error("Redis connection error during cleanup_expired: %s", exc)
            raise

    async def subscribe_revocation(self, lease_id: UUID) -> asyncio.Queue[str] | None:
        lease = await self.get(lease_id)
        if lease is None:
            return None
        await self._ensure_pubsub_listener()
        q: asyncio.Queue[str] = asyncio.Queue()
        async with self._lock:
            self._listeners.setdefault(lease_id, []).append(q)
        return q

    async def unsubscribe_revocation(
        self, lease_id: UUID, queue: asyncio.Queue[str]
    ) -> None:
        async with self._lock:
            listeners = self._listeners.get(lease_id)
            if listeners and queue in listeners:
                listeners.remove(queue)
                if not listeners:
                    self._listeners.pop(lease_id, None)

    async def mark_ws_connected(self, lease_id: UUID) -> bool:
        lease_hash_key = f"l4d:lease:{lease_id}"
        client = self._client
        try:
            async with self._lock:
                if lease_id in self._active_ws_leases:
                    return False
                local = self._leases_by_id.get(lease_id)
                if local is not None:
                    if local.ws_connected:
                        return False
                    local.ws_connected = True
                    local.ws_disconnected_at = None
                    self._active_ws_leases.add(lease_id)
            raw_data = await client.hgetall(lease_hash_key)
            if not raw_data and local is None:
                return False
            await client.hset(
                lease_hash_key,
                mapping={"ws_connected": "1", "ws_disconnected_at": ""},
            )
            async with self._lock:
                self._active_ws_leases.add(lease_id)
            return True
        except (RedisConnectionError, RedisTimeoutError) as exc:
            log.error(
                "Redis connection error in mark_ws_connected for lease_id=%s: %s",
                lease_id,
                exc,
            )
            raise

    async def mark_ws_disconnected(self, lease_id: UUID) -> None:
        now = datetime.now(UTC)
        lease_hash_key = f"l4d:lease:{lease_id}"
        client = self._client
        try:
            async with self._lock:
                local = self._leases_by_id.get(lease_id)
                if local is not None:
                    local.ws_connected = False
                    local.ws_disconnected_at = now
                self._active_ws_leases.discard(lease_id)
            await client.hset(
                lease_hash_key,
                mapping={
                    "ws_connected": "0",
                    "ws_disconnected_at": now.isoformat(),
                },
            )
        except (RedisConnectionError, RedisTimeoutError) as exc:
            log.error(
                "Redis connection error in mark_ws_disconnected for lease_id=%s: %s",
                lease_id,
                exc,
            )
            raise


lease_registry: LeaseRegistryProtocol = RedisLeaseRegistry()
