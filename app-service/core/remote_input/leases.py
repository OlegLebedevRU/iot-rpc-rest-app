from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from core.logging_config import setup_module_logger

log = setup_module_logger(__name__, "remote_input.log")


@dataclass(slots=True)
class Lease:
    lease_id: UUID
    org_id: int
    device_id: int
    sn: str
    owner_user_id: str
    owner_role: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_keepalive_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    revoked_reason: str | None = None
    listeners: list[asyncio.Queue[str]] = field(default_factory=list)

    def is_active(self, now: datetime | None = None) -> bool:
        if self.revoked_reason is not None:
            return False
        return (now or datetime.now(UTC)) < self.expires_at

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(UTC)) >= self.expires_at


class LeaseConflictError(Exception):
    def __init__(self, active_lease: Lease) -> None:
        self.active_lease = active_lease
        super().__init__(
            f"Lease busy on sn={active_lease.sn} by owner={active_lease.owner_user_id} expires_at={active_lease.expires_at.isoformat()}"
        )


class LeaseRegistryProtocol(Protocol):
    async def acquire(
        self,
        org_id: int,
        device_id: int,
        sn: str,
        owner_user_id: str,
        owner_role: str,
        ttl_sec: int,
    ) -> Lease: ...

    async def touch(self, lease_id: UUID, ttl_sec: int) -> Lease | None: ...

    async def revoke(
        self, lease_id: UUID, reason: str = "released"
    ) -> Lease | None: ...

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
    ) -> Lease:
        now = datetime.now(UTC)
        async with self._lock:
            existing_id = self._active_by_sn.get(sn)
            if existing_id is not None:
                existing = self._leases_by_id.get(existing_id)
                if existing is not None and existing.is_active(now):
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
                created_at=now,
                expires_at=expires_at,
                last_keepalive_at=now,
            )
            self._leases_by_id[lease_id] = lease
            self._active_by_sn[sn] = lease_id

        log.info(
            "Lease acquired: lease_id=%s sn=%s device_id=%s org_id=%s owner=%s expires_at=%s",
            lease.lease_id,
            sn,
            device_id,
            org_id,
            owner_user_id,
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

    async def revoke(self, lease_id: UUID, reason: str = "released") -> Lease | None:
        async with self._lock:
            lease = self._leases_by_id.get(lease_id)
            if lease is None:
                return None
            if lease.revoked_reason is None:
                lease.revoked_reason = reason
            if self._active_by_sn.get(lease.sn) == lease_id:
                self._active_by_sn.pop(lease.sn, None)
            listeners = list(lease.listeners)

        for q in listeners:
            try:
                q.put_nowait(reason)
            except Exception:
                pass

        log.info(
            "Lease revoked: lease_id=%s sn=%s reason=%s",
            lease_id,
            lease.sn,
            reason,
        )
        return lease

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
        expired: list[tuple[Lease, str]] = []
        listeners_to_notify: list[tuple[list[asyncio.Queue[str]], str]] = []

        async with self._lock:
            for sn, lease_id in list(self._active_by_sn.items()):
                lease = self._leases_by_id.get(lease_id)
                if lease is None or lease.is_expired(now):
                    self._active_by_sn.pop(sn, None)
                    if lease is not None:
                        if lease.revoked_reason is None:
                            lease.revoked_reason = "expired"
                        expired.append((lease, "expired"))
                        listeners_to_notify.append((list(lease.listeners), "expired"))

        for listeners, reason in listeners_to_notify:
            for q in listeners:
                try:
                    q.put_nowait(reason)
                except Exception:
                    pass

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
            self._active_ws_leases.add(lease_id)
            return True

    async def mark_ws_disconnected(self, lease_id: UUID) -> None:
        async with self._lock:
            self._active_ws_leases.discard(lease_id)


lease_registry: LeaseRegistryProtocol = LeaseRegistry()
