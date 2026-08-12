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
from core.diagnostics.service import DeviceTaskDiagnosticTaskSender, DiagnosticService
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
async def test_service_accepts_mssql_query_command_id():
    sender = RecordingSender()
    service = DiagnosticService(DiagnosticsSessionRegistry(), sender)

    session = await service.exec(
        "SN001",
        ExecDiagnosticMessage(type="exec", command_id="mssql_query"),
    )

    assert session.command_id == "mssql_query"
    assert len(sender.sent) == 1
    assert sender.sent[0][1].method_code == CMD_DIAG_EXEC
    assert sender.sent[0][1].payload.dt[0].command_id == "mssql_query"


@pytest.mark.asyncio
async def test_service_rejects_unknown_command_id():
    service = DiagnosticService(DiagnosticsSessionRegistry(), RecordingSender())

    with pytest.raises(ValueError):
        await service.exec(
            "SN001",
            ExecDiagnosticMessage(type="exec", command_id="rm_rf"),
        )


@pytest.mark.asyncio
async def test_service_accepts_mssql_query():
    sender = RecordingSender()
    service = DiagnosticService(DiagnosticsSessionRegistry(), sender)

    session = await service.exec(
        "SN001",
        ExecDiagnosticMessage(type="exec", command_id="mssql_query"),
    )

    assert session.command_id == "mssql_query"
    assert sender.sent[0][1].payload.dt[0].command_id == "mssql_query"


def test_allowlist_contains_all_expected_commands():
    from core.diagnostics.commands import DIAGNOSTIC_COMMANDS

    expected = {
        # Basic
        "system_info",
        "echo",
        "time",
        # Universal
        "network_info",
        "disk_usage",
        "service_status",
        # Linux
        "uptime",
        "memory_usage",
        "process_list",
        "top_processes",
        "journal_logs",
        "iptables_rules",
        "systemctl_status",
        # Windows
        "get_processes",
        "get_services",
        "event_log",
        "disk_info",
        "cpu_usage",
        "network_config",
        "os_version",
        "mssql_query",
        # Utility
        "list_commands",
    }

    assert set(DIAGNOSTIC_COMMANDS) == expected


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


@pytest.mark.asyncio
async def test_device_task_sender_creates_existing_rpc_task(monkeypatch):
    created_tasks = []

    async def fake_get_device_id(*, session, sn, org_id):
        assert sn == "SN001"
        assert org_id == 7
        return 123

    async def fake_create(self, task_create):
        created_tasks.append(task_create)

    monkeypatch.setattr(
        "core.diagnostics.service.DeviceRepo.get_device_id",
        fake_get_device_id,
    )
    monkeypatch.setattr(
        "core.diagnostics.service.DeviceTasksService.create",
        fake_create,
    )

    service = DiagnosticService(
        DiagnosticsSessionRegistry(),
        DeviceTaskDiagnosticTaskSender(session=object(), org_id=7),  # type: ignore[arg-type]
    )

    session = await service.start_log(
        "SN001",
        StartLogMessage(type="start_log", level="debug", ttl_sec=120),
    )

    assert len(created_tasks) == 1
    task = created_tasks[0]
    assert task.device_id == 123
    assert task.method_code == CMD_DIAG_STREAM_CONTROL
    assert task.ttl == 2
    assert task.payload == {
        "dt": [
            {
                "action": "start",
                "session_id": str(session.session_id),
                "stream": "esp32-log",
                "level": "debug",
                "ttl_sec": 120,
                "max_rate_bps": 8192,
                "topic": "dev/SN001/out",
            }
        ]
    }
