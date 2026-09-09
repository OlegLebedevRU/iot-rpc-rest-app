from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from core.config import settings
from core.logging_config import setup_module_logger
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
                        if existing.scope == scope:
                            existing.last_keepalive_at = now
                            existing.expires_at = now + timedelta(seconds=ttl_sec)
                            return existing
                        else:
                            # Upgrade scope
                            existing.scope = scope
                            existing.last_keepalive_at = now
                            existing.expires_at = now + timedelta(seconds=ttl_sec)
                            return existing
                    else:
                        raise LeaseConflictError(existing)
                # If expired/revoked, remove stale mapping
                self._active_by_sn.pop(sn, None)

            lease_id = uuid4()
            expires_at = now + timedelta(seconds=ttl_sec)
            lease = Lease(
                lease_id=lease_id,
                org_id=org_id,
                device_id=device_id,
                sn=sn,
                owner_user_id=owner_user_id,
                owner_role=owner_role,
                scope=scope,
                owner_session_id=owner_session_id,
                stream_mode="desktop" if scope == "input" else None,
                created_at=now,
                expires_at=expires_at,
                last_keepalive_at=now,
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
            return lease

    async def revoke(self, lease_id: UUID, reason: str = "released") -> Lease | None:
        async with self._lock:
            lease = self._leases_by_id.get(lease_id)
            if lease is None:
                return None
            if lease.revoked_reason is None:
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


lease_registry: LeaseRegistryProtocol = LeaseRegistry()
