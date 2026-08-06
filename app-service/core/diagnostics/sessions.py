from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from core.diagnostics.schemas import (
    BackendStatusMessage,
    DeviceOutputEnvelope,
    DiagnosticSessionKind,
    output_to_backend_message,
)


@dataclass(slots=True)
class DiagnosticSession:
    sn: str
    session_id: UUID
    kind: DiagnosticSessionKind
    ttl_sec: int
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    command_id: str | None = None
    stream: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    closing: bool = False
    bytes_sent: int = 0

    @property
    def expires_at(self) -> datetime:
        return self.created_at + timedelta(seconds=self.ttl_sec)

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(UTC)) >= self.expires_at


class DiagnosticsSessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[tuple[str, UUID], DiagnosticSession] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _key(sn: str, session_id: UUID) -> tuple[str, UUID]:
        return sn, session_id

    async def register(self, session: DiagnosticSession) -> DiagnosticSession:
        async with self._lock:
            self._sessions[self._key(session.sn, session.session_id)] = session
        await session.queue.put(
            BackendStatusMessage(session_id=session.session_id, status="started")
        )
        return session

    async def get(self, sn: str, session_id: UUID) -> DiagnosticSession | None:
        async with self._lock:
            session = self._sessions.get(self._key(sn, session_id))
            if session is None:
                return None
            if session.closing or session.is_expired():
                return None
            return session

    async def mark_closing(self, sn: str, session_id: UUID) -> DiagnosticSession | None:
        async with self._lock:
            session = self._sessions.get(self._key(sn, session_id))
            if session is not None:
                session.closing = True
            return session

    async def remove(self, sn: str, session_id: UUID) -> DiagnosticSession | None:
        async with self._lock:
            return self._sessions.pop(self._key(sn, session_id), None)

    async def remove_all_for_sn(self, sn: str) -> list[DiagnosticSession]:
        async with self._lock:
            removed: list[DiagnosticSession] = []
            for key, session in list(self._sessions.items()):
                if key[0] == sn:
                    removed.append(self._sessions.pop(key))
            return removed

    async def route_output(self, sn: str, envelope: DeviceOutputEnvelope) -> bool:
        session = await self.get(sn, envelope.session_id)
        if session is None:
            return False

        message = output_to_backend_message(sn, envelope)
        session.bytes_sent += len(envelope.data.encode("utf-8"))
        await session.queue.put(message)
        return True

    async def cleanup_expired(self) -> list[DiagnosticSession]:
        now = datetime.now(UTC)
        async with self._lock:
            expired_keys = [
                key
                for key, session in self._sessions.items()
                if session.is_expired(now)
            ]
            return [self._sessions.pop(key) for key in expired_keys]

    async def list_active(self) -> list[DiagnosticSession]:
        async with self._lock:
            return [
                session
                for session in self._sessions.values()
                if not session.closing and not session.is_expired()
            ]


registry = DiagnosticsSessionRegistry()
