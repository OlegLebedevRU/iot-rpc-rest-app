from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    TimeoutError as RedisTimeoutError,
)

from core.diagnostics.schemas import (
    BackendStatusMessage,
    DeviceOutputEnvelope,
    DiagnosticSessionKind,
    output_to_backend_message,
)
from core.logging_config import setup_module_logger
from core.redis_helper import redis_helper

log = setup_module_logger(__name__, "diagnostics.log")


@dataclass(slots=True)
class DiagnosticSession:
    sn: str
    session_id: UUID | str
    kind: DiagnosticSessionKind
    ttl_sec: int
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    command_id: str | None = None
    stream: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    closing: bool = False
    bytes_sent: int = 0
    seen_seqs: set[int] = field(default_factory=set)

    @property
    def expires_at(self) -> datetime:
        return self.created_at + timedelta(seconds=self.ttl_sec)

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(UTC)) >= self.expires_at


class DiagnosticsSessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str], DiagnosticSession] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _key(sn: str, session_id: UUID | str) -> tuple[str, str]:
        return sn, str(session_id)

    async def register(self, session: DiagnosticSession) -> DiagnosticSession:
        async with self._lock:
            self._sessions[self._key(session.sn, session.session_id)] = session
        await session.queue.put(
            BackendStatusMessage(session_id=session.session_id, status="started")
        )
        return session

    async def get(self, sn: str, session_id: UUID | str) -> DiagnosticSession | None:
        async with self._lock:
            session = self._sessions.get(self._key(sn, session_id))
            if session is None:
                return None
            if session.closing or session.is_expired():
                return None
            return session

    async def mark_closing(
        self, sn: str, session_id: UUID | str
    ) -> DiagnosticSession | None:
        async with self._lock:
            session = self._sessions.get(self._key(sn, session_id))
            if session is not None:
                session.closing = True
            return session

    async def remove(self, sn: str, session_id: UUID | str) -> DiagnosticSession | None:
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

        if envelope.seq in session.seen_seqs:
            return True

        session.seen_seqs.add(envelope.seq)
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


class RedisDiagnosticsSessionRegistry(DiagnosticsSessionRegistry):
    @property
    def _client(self):
        return redis_helper.get_client()

    async def register(self, session: DiagnosticSession) -> DiagnosticSession:
        res = await super().register(session)
        client = self._client
        diag_key = f"l4d:diag:session:{session.session_id}"
        try:
            await client.hset(
                diag_key,
                mapping={
                    "sn": session.sn,
                    "session_id": str(session.session_id),
                    "kind": str(session.kind),
                    "ttl_sec": str(session.ttl_sec),
                    "command_id": str(session.command_id or ""),
                    "stream": str(session.stream or ""),
                    "created_at": session.created_at.isoformat(),
                    "closing": "1" if session.closing else "0",
                    "bytes_sent": str(session.bytes_sent),
                },
            )
            await client.expire(diag_key, session.ttl_sec)
        except (RedisConnectionError, RedisTimeoutError) as exc:
            log.warning("Redis error during register diag session: %s", exc)
        return res

    async def get(self, sn: str, session_id: UUID | str) -> DiagnosticSession | None:
        sess = await super().get(sn, session_id)
        if sess is not None:
            return sess
        client = self._client
        diag_key = f"l4d:diag:session:{session_id}"
        try:
            raw = await client.hgetall(diag_key)
            if raw and raw.get("sn") == sn and raw.get("closing") != "1":
                created_at = datetime.fromisoformat(raw["created_at"])
                ttl_sec = int(raw.get("ttl_sec", 60))
                now = datetime.now(UTC)
                if (now - created_at).total_seconds() < ttl_sec:
                    restored = DiagnosticSession(
                        sn=sn,
                        session_id=session_id,
                        kind=raw.get("kind", "output"),  # type: ignore
                        ttl_sec=ttl_sec,
                        command_id=raw.get("command_id") or None,
                        stream=raw.get("stream") or None,
                        created_at=created_at,
                        closing=False,
                        bytes_sent=int(raw.get("bytes_sent", 0)),
                    )
                    async with self._lock:
                        self._sessions[self._key(sn, session_id)] = restored
                    return restored
        except (RedisConnectionError, RedisTimeoutError) as exc:
            log.warning("Redis error during get diag session: %s", exc)
        return None

    async def mark_closing(
        self, sn: str, session_id: UUID | str
    ) -> DiagnosticSession | None:
        res = await super().mark_closing(sn, session_id)
        client = self._client
        diag_key = f"l4d:diag:session:{session_id}"
        try:
            if await client.exists(diag_key):
                await client.hset(diag_key, "closing", "1")
        except (RedisConnectionError, RedisTimeoutError) as exc:
            log.warning("Redis error during mark_closing diag session: %s", exc)
        return res

    async def remove(self, sn: str, session_id: UUID | str) -> DiagnosticSession | None:
        res = await super().remove(sn, session_id)
        client = self._client
        diag_key = f"l4d:diag:session:{session_id}"
        try:
            await client.delete(diag_key)
        except (RedisConnectionError, RedisTimeoutError) as exc:
            log.warning("Redis error during remove diag session: %s", exc)
        return res

    async def remove_all_for_sn(self, sn: str) -> list[DiagnosticSession]:
        removed = await super().remove_all_for_sn(sn)
        client = self._client
        try:
            keys = await client.keys("l4d:diag:session:*")
            for k in keys:
                sess_sn = await client.hget(k, "sn")
                if sess_sn == sn:
                    await client.delete(k)
        except (RedisConnectionError, RedisTimeoutError) as exc:
            log.warning("Redis error during remove_all_for_sn diag sessions: %s", exc)
        return removed

    async def cleanup_expired(self) -> list[DiagnosticSession]:
        removed = await super().cleanup_expired()
        client = self._client
        now = datetime.now(UTC)
        try:
            keys = await client.keys("l4d:diag:session:*")
            for k in keys:
                created_raw = await client.hget(k, "created_at")
                ttl_raw = await client.hget(k, "ttl_sec")
                if created_raw and ttl_raw:
                    dt = datetime.fromisoformat(created_raw)
                    ttl = int(ttl_raw)
                    if (now - dt).total_seconds() >= ttl:
                        await client.delete(k)
        except (RedisConnectionError, RedisTimeoutError) as exc:
            log.warning("Redis error during cleanup_expired diag sessions: %s", exc)
        return removed


registry = RedisDiagnosticsSessionRegistry()
diagnostics_session_registry = registry
