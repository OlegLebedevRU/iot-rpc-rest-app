from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from core.config import settings
from core.logging_config import setup_module_logger

log = setup_module_logger(__name__, "remote_input.log")


@dataclass(slots=True)
class PendingResult:
    result: str
    code: str | None = None
    message: str | None = None
    terminal_time_ms: int | None = None
    stream_instance_id: UUID | None = None
    state: str | None = None
    inventory: Any | None = None


@dataclass(slots=True)
class PendingCommand:
    command_id: UUID
    lease_id: UUID | None
    sn: str
    cmd_type: str
    issued_at: float
    future: asyncio.Future[PendingResult]
    timeout_sec: float | None = None


class PendingCommandRegistryProtocol(Protocol):
    async def register(
        self,
        command_id: UUID,
        lease_id: UUID | None,
        sn: str,
        cmd_type: str,
        timeout_sec: float | None = None,
    ) -> asyncio.Future[PendingResult]: ...

    async def resolve(self, command_id: UUID, result: PendingResult) -> bool: ...

    async def cancel_for_lease(
        self, lease_id: UUID, reason: str = "lease_revoked"
    ) -> int: ...

    async def expire(self, timeout_sec: float | None = None) -> list[UUID]: ...


class PendingCommandRegistry:
    def __init__(self) -> None:
        self._pending: dict[UUID, PendingCommand] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        command_id: UUID,
        lease_id: UUID | None,
        sn: str,
        cmd_type: str,
        timeout_sec: float | None = None,
    ) -> asyncio.Future[PendingResult]:
        async with self._lock:
            if len(self._pending) >= settings.remote_input.pending_max_total:
                raise RuntimeError("Max total pending commands limit exceeded")

            if lease_id is not None:
                lease_count = sum(
                    1 for cmd in self._pending.values() if cmd.lease_id == lease_id
                )
                if lease_count >= settings.remote_input.pending_max_per_lease:
                    raise RuntimeError("Max pending commands limit per lease exceeded")

            loop = asyncio.get_running_loop()
            future: asyncio.Future[PendingResult] = loop.create_future()
            self._pending[command_id] = PendingCommand(
                command_id=command_id,
                lease_id=lease_id,
                sn=sn,
                cmd_type=cmd_type,
                issued_at=time.monotonic(),
                future=future,
                timeout_sec=timeout_sec,
            )
            return future

    async def resolve(self, command_id: UUID, result: PendingResult) -> bool:
        async with self._lock:
            cmd = self._pending.pop(command_id, None)
            if cmd is None:
                return False
            if not cmd.future.done():
                cmd.future.set_result(result)
            return True

    async def cancel_for_lease(
        self, lease_id: UUID, reason: str = "lease_revoked"
    ) -> int:
        cancelled = 0
        async with self._lock:
            for cmd_id, cmd in list(self._pending.items()):
                if cmd.lease_id == lease_id:
                    self._pending.pop(cmd_id, None)
                    if not cmd.future.done():
                        cmd.future.set_result(
                            PendingResult(
                                result="unconfirmed",
                                code=reason,
                                message=f"Cancelled: {reason}",
                            )
                        )
                    cancelled += 1
        return cancelled

    async def expire(self, timeout_sec: float | None = None) -> list[UUID]:
        default_timeout = (
            settings.remote_input.click_ack_timeout_ms / 1000.0
            if timeout_sec is None
            else timeout_sec
        )

        now = time.monotonic()
        expired_ids: list[UUID] = []
        async with self._lock:
            for cmd_id, cmd in list(self._pending.items()):
                cmd_timeout = (
                    cmd.timeout_sec if cmd.timeout_sec is not None else default_timeout
                )
                if (now - cmd.issued_at) > cmd_timeout:
                    self._pending.pop(cmd_id, None)
                    if not cmd.future.done():
                        cmd.future.set_result(
                            PendingResult(
                                result="unconfirmed",
                                code="expired",
                                message="Command expired in pending registry",
                            )
                        )
                    expired_ids.append(cmd_id)
        return expired_ids


pending_registry: PendingCommandRegistryProtocol = PendingCommandRegistry()
