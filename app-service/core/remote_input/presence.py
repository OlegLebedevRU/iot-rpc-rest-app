from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Protocol

from core.config import settings
from core.logging_config import setup_module_logger
from core.remote_input.schemas import AgentStatusView, CtlPresence

log = setup_module_logger(__name__, "remote_input.log")


class PresenceRegistryProtocol(Protocol):
    async def update(
        self, sn: str, presence: CtlPresence
    ) -> tuple[bool, AgentStatusView]: ...

    async def get(self, sn: str) -> AgentStatusView: ...

    async def subscribe(self, sn: str) -> asyncio.Queue[AgentStatusView]: ...

    async def unsubscribe(
        self, sn: str, queue: asyncio.Queue[AgentStatusView]
    ) -> None: ...


class PresenceRegistry:
    def __init__(self) -> None:
        self._presence: dict[str, tuple[CtlPresence, datetime]] = {}
        self._listeners: dict[str, list[asyncio.Queue[AgentStatusView]]] = {}
        self._lock = asyncio.Lock()

    def _build_view(
        self, presence: CtlPresence, received_at: datetime, now: datetime
    ) -> AgentStatusView:
        age_sec = (now - received_at).total_seconds()
        stale = age_sec >= settings.remote_input.presence_stale_sec
        online = (presence.status == "online") and (not stale)
        desktop_available = presence.desktop_available if online else False
        screen = presence.screen if online else None

        return AgentStatusView(
            online=online,
            desktop_available=desktop_available,
            screen=screen,
            last_seen_at=presence.timestamp,
            stale=stale,
        )

    async def update(
        self, sn: str, presence: CtlPresence
    ) -> tuple[bool, AgentStatusView]:
        now = datetime.now(UTC)
        async with self._lock:
            prev = self._presence.get(sn)
            prev_status = prev[0].status if prev else None
            prev_desktop = prev[0].desktop_available if prev else None

            self._presence[sn] = (presence, now)
            view = self._build_view(presence, now, now)

            changed = (prev_status != presence.status) or (
                prev_desktop != presence.desktop_available
            )
            if changed:
                log.info(
                    "Presence state changed for sn=%s: status=%s->%s, desktop_available=%s->%s",
                    sn,
                    prev_status,
                    presence.status,
                    prev_desktop,
                    presence.desktop_available,
                )

            listeners = list(self._listeners.get(sn, []))

        # Notify listeners outside the lock
        for q in listeners:
            try:
                q.put_nowait(view)
            except Exception:
                pass

        return changed, view

    async def get(self, sn: str) -> AgentStatusView:
        now = datetime.now(UTC)
        async with self._lock:
            record = self._presence.get(sn)
            if record is None:
                return AgentStatusView(
                    online=False,
                    desktop_available=False,
                    screen=None,
                    last_seen_at=None,
                    stale=True,
                )
            presence, received_at = record
            return self._build_view(presence, received_at, now)

    async def subscribe(self, sn: str) -> asyncio.Queue[AgentStatusView]:
        q: asyncio.Queue[AgentStatusView] = asyncio.Queue()
        async with self._lock:
            self._listeners.setdefault(sn, []).append(q)
        return q

    async def unsubscribe(self, sn: str, queue: asyncio.Queue[AgentStatusView]) -> None:
        async with self._lock:
            listeners = self._listeners.get(sn)
            if listeners and queue in listeners:
                listeners.remove(queue)
                if not listeners:
                    self._listeners.pop(sn, None)


presence_registry: PresenceRegistryProtocol = PresenceRegistry()
