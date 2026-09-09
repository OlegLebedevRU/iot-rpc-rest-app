from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Protocol

from core.config import settings
from core.logging_config import setup_module_logger
from core.remote_input.schemas import (
    AgentStatusView,
    CtlPresence,
    CtlStreamEvent,
    InventoryInfo,
    StreamInfo,
    WsStreamState,
)

log = setup_module_logger(__name__, "remote_input.log")


class PresenceRegistryProtocol(Protocol):
    async def update(
        self, sn: str, presence: CtlPresence
    ) -> tuple[bool, AgentStatusView]: ...

    async def update_stream_event(
        self, sn: str, event: CtlStreamEvent
    ) -> WsStreamState: ...

    async def update_inventory(self, sn: str, inventory: InventoryInfo) -> None: ...

    async def get(self, sn: str) -> AgentStatusView: ...

    async def get_inventory(self, sn: str) -> InventoryInfo: ...

    async def get_stream(self, sn: str) -> StreamInfo: ...

    async def subscribe(self, sn: str) -> asyncio.Queue[AgentStatusView]: ...

    async def unsubscribe(
        self, sn: str, queue: asyncio.Queue[AgentStatusView]
    ) -> None: ...

    async def subscribe_stream(self, sn: str) -> asyncio.Queue[WsStreamState]: ...

    async def unsubscribe_stream(
        self, sn: str, queue: asyncio.Queue[WsStreamState]
    ) -> None: ...


class PresenceRegistry:
    def __init__(self) -> None:
        self._presence: dict[str, tuple[CtlPresence, datetime]] = {}
        self._last_inventory: dict[str, InventoryInfo] = {}
        self._last_stream: dict[str, StreamInfo] = {}
        self._listeners: dict[str, list[asyncio.Queue[AgentStatusView]]] = {}
        self._stream_listeners: dict[str, list[asyncio.Queue[WsStreamState]]] = {}
        self._lock = asyncio.Lock()

    def _build_view(
        self, sn: str, presence: CtlPresence, received_at: datetime, now: datetime
    ) -> AgentStatusView:
        age_sec = (now - received_at).total_seconds()
        stale = age_sec >= settings.remote_input.presence_stale_sec
        online = (presence.status == "online") and (not stale)
        desktop_available = presence.desktop_available if online else False
        session_id = presence.session_id if online else None
        screen = presence.screen if online else None
        inventory = (
            (presence.inventory or self._last_inventory.get(sn)) if online else None
        )
        stream = (presence.stream or self._last_stream.get(sn)) if online else None

        return AgentStatusView(
            online=online,
            desktop_available=desktop_available,
            session_id=session_id,
            screen=screen,
            inventory=inventory,
            stream=stream,
            last_seen_at=presence.timestamp,
            stale=stale,
        )

    async def update(
        self, sn: str, presence: CtlPresence
    ) -> tuple[bool, AgentStatusView]:
        now = datetime.now(UTC)
        stream_event_to_dispatch: WsStreamState | None = None

        async with self._lock:
            if presence.inventory is not None:
                self._last_inventory[sn] = presence.inventory
            if presence.stream is not None:
                prev_stream = self._last_stream.get(sn)
                self._last_stream[sn] = presence.stream
                if prev_stream is None or prev_stream.state != presence.stream.state:
                    stream_event_to_dispatch = WsStreamState(
                        stream_instance_id=presence.stream.stream_instance_id,
                        state=presence.stream.state,
                        reason=presence.stream.reason,
                        timestamp=presence.timestamp,
                    )

            prev = self._presence.get(sn)
            prev_status = prev[0].status if prev else None
            prev_desktop = prev[0].desktop_available if prev else None

            self._presence[sn] = (presence, now)
            view = self._build_view(sn, presence, now, now)

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
            stream_listeners = (
                list(self._stream_listeners.get(sn, []))
                if stream_event_to_dispatch
                else []
            )

        for q in listeners:
            try:
                q.put_nowait(view)
            except Exception:
                pass

        if stream_event_to_dispatch:
            for sq in stream_listeners:
                try:
                    sq.put_nowait(stream_event_to_dispatch)
                except Exception:
                    pass

        return changed, view

    async def update_stream_event(
        self, sn: str, event: CtlStreamEvent
    ) -> WsStreamState:
        now = datetime.now(UTC)
        async with self._lock:
            current_stream = self._last_stream.get(sn) or StreamInfo()
            current_stream.state = event.state
            if event.stream_instance_id is not None:
                current_stream.stream_instance_id = event.stream_instance_id
            current_stream.reason = event.reason
            self._last_stream[sn] = current_stream

            # If presence exists, update its stream reference too
            rec = self._presence.get(sn)
            if rec is not None:
                p, r_at = rec
                p.stream = current_stream

            ws_state = WsStreamState(
                stream_instance_id=current_stream.stream_instance_id,
                state=event.state,
                reason=event.reason,
                timestamp=event.timestamp,
            )
            stream_listeners = list(self._stream_listeners.get(sn, []))

            # Also build updated view for status listeners
            if rec is not None:
                p, r_at = rec
                view = self._build_view(sn, p, r_at, now)
                status_listeners = list(self._listeners.get(sn, []))
            else:
                status_listeners = []
                view = None

        for sq in stream_listeners:
            try:
                sq.put_nowait(ws_state)
            except Exception:
                pass

        if view is not None:
            for q in status_listeners:
                try:
                    q.put_nowait(view)
                except Exception:
                    pass

        log.info(
            "Stream event updated for sn=%s: state=%s instance=%s reason=%s",
            sn,
            event.state,
            event.stream_instance_id,
            event.reason,
        )
        return ws_state

    async def update_inventory(self, sn: str, inventory: InventoryInfo) -> None:
        async with self._lock:
            self._last_inventory[sn] = inventory
            rec = self._presence.get(sn)
            if rec is not None:
                p, _ = rec
                p.inventory = inventory

    async def get(self, sn: str) -> AgentStatusView:
        now = datetime.now(UTC)
        async with self._lock:
            record = self._presence.get(sn)
            if record is None:
                return AgentStatusView(
                    online=False,
                    desktop_available=False,
                    session_id=None,
                    screen=None,
                    inventory=None,
                    stream=None,
                    last_seen_at=None,
                    stale=True,
                )
            presence, received_at = record
            return self._build_view(sn, presence, received_at, now)

    async def get_inventory(self, sn: str) -> InventoryInfo:
        async with self._lock:
            return self._last_inventory.get(sn) or InventoryInfo()

    async def get_stream(self, sn: str) -> StreamInfo:
        async with self._lock:
            return self._last_stream.get(sn) or StreamInfo()

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

    async def subscribe_stream(self, sn: str) -> asyncio.Queue[WsStreamState]:
        q: asyncio.Queue[WsStreamState] = asyncio.Queue()
        async with self._lock:
            self._stream_listeners.setdefault(sn, []).append(q)
        return q

    async def unsubscribe_stream(
        self, sn: str, queue: asyncio.Queue[WsStreamState]
    ) -> None:
        async with self._lock:
            listeners = self._stream_listeners.get(sn)
            if listeners and queue in listeners:
                listeners.remove(queue)
                if not listeners:
                    self._stream_listeners.pop(sn, None)


presence_registry: PresenceRegistryProtocol = PresenceRegistry()
