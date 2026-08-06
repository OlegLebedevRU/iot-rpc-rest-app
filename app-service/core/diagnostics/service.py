from __future__ import annotations

from typing import Protocol
from uuid import UUID, uuid4

from core.diagnostics.commands import is_known_command
from core.diagnostics.schemas import (
    BackendErrorMessage,
    BackendStatusMessage,
    CancelDiagnosticMessage,
    DiagnosticRpcTask,
    DiagnosticSessionKind,
    ExecDiagnosticMessage,
    StartLogMessage,
    StopLogMessage,
    build_cancel_task,
    build_exec_task,
    build_start_log_task,
    build_stop_log_task,
)
from core.diagnostics.sessions import DiagnosticSession, DiagnosticsSessionRegistry


class DiagnosticTaskSender(Protocol):
    async def send(self, sn: str, task: DiagnosticRpcTask) -> None: ...


class NoopDiagnosticTaskSender:
    """MVP sender used by API skeleton until DB/RPC integration is wired."""

    async def send(self, sn: str, task: DiagnosticRpcTask) -> None:
        return None


class DiagnosticService:
    def __init__(
        self,
        registry: DiagnosticsSessionRegistry,
        task_sender: DiagnosticTaskSender | None = None,
    ) -> None:
        self.registry = registry
        self.task_sender = task_sender or NoopDiagnosticTaskSender()

    async def start_log(self, sn: str, message: StartLogMessage) -> DiagnosticSession:
        session = DiagnosticSession(
            sn=sn,
            session_id=uuid4(),
            kind=DiagnosticSessionKind.LIVE_LOG,
            ttl_sec=message.ttl_sec,
            stream=message.stream,
        )
        await self.registry.register(session)
        await self.task_sender.send(
            sn,
            build_start_log_task(
                session_id=session.session_id,
                sn=sn,
                level=message.level,
                stream=message.stream,
                ttl_sec=message.ttl_sec,
                max_rate_bps=message.max_rate_bps,
            ),
        )
        return session

    async def stop_log(self, sn: str, message: StopLogMessage) -> bool:
        session = await self.registry.mark_closing(sn, message.session_id)
        await self.task_sender.send(
            sn,
            build_stop_log_task(session_id=message.session_id, stream=message.stream),
        )
        await self.registry.remove(sn, message.session_id)
        return session is not None

    async def exec(self, sn: str, message: ExecDiagnosticMessage) -> DiagnosticSession:
        if not is_known_command(message.command_id):
            raise ValueError(f"unknown diagnostic command_id: {message.command_id}")

        session = DiagnosticSession(
            sn=sn,
            session_id=uuid4(),
            kind=DiagnosticSessionKind.EXEC,
            ttl_sec=message.ttl_sec,
            command_id=message.command_id,
        )
        await self.registry.register(session)
        await self.task_sender.send(
            sn,
            build_exec_task(
                session_id=session.session_id,
                sn=sn,
                command_id=message.command_id,
                args=message.args,
                ttl_sec=message.ttl_sec,
                max_output_bytes=message.max_output_bytes,
            ),
        )
        return session

    async def cancel(self, sn: str, message: CancelDiagnosticMessage) -> bool:
        session = await self.registry.mark_closing(sn, message.session_id)
        await self.task_sender.send(
            sn,
            build_cancel_task(session_id=message.session_id, reason=message.reason),
        )
        await self.registry.remove(sn, message.session_id)
        return session is not None

    async def close_session(
        self,
        sn: str,
        session_id: UUID,
        reason: str = "browser_closed",
    ) -> bool:
        session = await self.registry.mark_closing(sn, session_id)
        if session is None:
            return False

        if session.kind is DiagnosticSessionKind.LIVE_LOG:
            await self.task_sender.send(
                sn,
                build_stop_log_task(
                    session_id=session.session_id,
                    stream=session.stream or "esp32-log",
                ),
            )
        elif session.kind is DiagnosticSessionKind.EXEC:
            await self.task_sender.send(
                sn,
                build_cancel_task(session_id=session.session_id, reason=reason),
            )

        await self.registry.remove(sn, session_id)
        return True

    async def emit_status(self, session: DiagnosticSession, status: str) -> None:
        await session.queue.put(
            BackendStatusMessage(session_id=session.session_id, status=status)
        )

    async def emit_error(
        self,
        session: DiagnosticSession | None,
        error: str,
    ) -> None:
        if session is not None:
            await session.queue.put(
                BackendErrorMessage(session_id=session.session_id, error=error)
            )
