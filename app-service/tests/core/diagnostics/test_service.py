from __future__ import annotations

from uuid import UUID

import pytest

from core.diagnostics.commands import (
    CMD_DIAG_CANCEL,
    CMD_DIAG_EXEC,
    CMD_DIAG_STREAM_CONTROL,
)
from core.diagnostics.schemas import (
    CancelDiagnosticMessage,
    ExecDiagnosticMessage,
    StartLogMessage,
    StopLogMessage,
)
from core.diagnostics.service import DiagnosticService
from core.diagnostics.sessions import DiagnosticsSessionRegistry


class RecordingSender:
    def __init__(self) -> None:
        self.sent = []

    async def send(self, sn, task) -> None:
        self.sent.append((sn, task))


@pytest.mark.asyncio
async def test_service_creates_start_and_stop_log_payloads():
    sender = RecordingSender()
    service = DiagnosticService(DiagnosticsSessionRegistry(), sender)

    session = await service.start_log(
        "SN001",
        StartLogMessage(type="start_log", level="debug", ttl_sec=120),
    )
    stopped = await service.stop_log(
        "SN001",
        StopLogMessage(type="stop_log", session_id=session.session_id),
    )

    assert stopped is True
    assert [task.method_code for _, task in sender.sent] == [
        CMD_DIAG_STREAM_CONTROL,
        CMD_DIAG_STREAM_CONTROL,
    ]
    assert sender.sent[0][1].payload.dt[0].topic == "dev/SN001/out"
    assert sender.sent[1][1].payload.dt[0].action == "stop"


@pytest.mark.asyncio
async def test_service_creates_exec_and_cancel_payloads():
    sender = RecordingSender()
    service = DiagnosticService(DiagnosticsSessionRegistry(), sender)

    session = await service.exec(
        "SN001",
        ExecDiagnosticMessage(
            type="exec",
            command_id="system_info",
            args={"verbose": True},
            ttl_sec=60,
        ),
    )
    cancelled = await service.cancel(
        "SN001",
        CancelDiagnosticMessage(
            type="cancel",
            session_id=session.session_id,
            reason="browser_closed",
        ),
    )

    assert cancelled is True
    assert [task.method_code for _, task in sender.sent] == [
        CMD_DIAG_EXEC,
        CMD_DIAG_CANCEL,
    ]
    assert sender.sent[0][1].payload.dt[0].command_id == "system_info"
    assert sender.sent[1][1].payload.dt[0].reason == "browser_closed"


@pytest.mark.asyncio
async def test_service_rejects_unknown_command_id():
    service = DiagnosticService(DiagnosticsSessionRegistry(), RecordingSender())

    with pytest.raises(ValueError):
        await service.exec(
            "SN001",
            ExecDiagnosticMessage(type="exec", command_id="rm_rf"),
        )


@pytest.mark.asyncio
async def test_close_browser_sends_cancel_for_active_exec_session():
    sender = RecordingSender()
    service = DiagnosticService(DiagnosticsSessionRegistry(), sender)
    session = await service.exec(
        "SN001",
        ExecDiagnosticMessage(type="exec", command_id="system_info"),
    )

    closed = await service.close_session(
        "SN001",
        UUID(str(session.session_id)),
        reason="browser_closed",
    )

    assert closed is True
    assert [task.method_code for _, task in sender.sent] == [
        CMD_DIAG_EXEC,
        CMD_DIAG_CANCEL,
    ]
    assert sender.sent[-1][1].payload.dt[0].reason == "browser_closed"
