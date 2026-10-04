from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.diagnostics.schemas import DiagnosticRpcTask
from core.rpc_redaction import redact_rpc
from core.schemas.device_tasks import TaskCreate


@pytest.mark.parametrize("method", [7000, 7001, 7002])
@pytest.mark.parametrize(
    "shape", ["missing", "null", "object", "scalar", "empty", "one", "two", "wrong"]
)
def test_method_body_matrix(method, shape):
    sid = str(uuid4())
    items = {
        7000: {"session_id": sid, "action": "stop"},
        7001: {"session_id": sid, "command_line": "echo fixture"},
        7002: {"session_id": sid, "reason": "operator"},
    }
    values = {
        "missing": {},
        "null": {"dt": None},
        "object": {"dt": items[method]},
        "scalar": {"dt": "fixture"},
        "empty": {"dt": []},
        "one": {"dt": [items[method]]},
        "two": {"dt": [items[method], items[method]]},
        "wrong": {"dt": [{"session_id": sid, "unrecognized": True}]},
    }
    value = {"method_code": method, "payload": values[shape]}
    valid = shape == "one" or (method == 7002 and shape == "empty")
    if valid:
        assert DiagnosticRpcTask.model_validate(value).method_code == method
        assert TaskCreate(device_id=1, ext_task_id="fixture", **value).payload
    else:
        with pytest.raises(ValidationError):
            DiagnosticRpcTask.model_validate(value)
        with pytest.raises(ValidationError):
            TaskCreate(device_id=1, ext_task_id="fixture", **value)


@pytest.mark.parametrize("method", [7000, 7002])
def test_exec_item_does_not_validate_as_another_method(method):
    with pytest.raises(ValidationError):
        DiagnosticRpcTask.model_validate(
            {
                "method_code": method,
                "payload": {"dt": [{"session_id": str(uuid4()), "command_line": "x"}]},
            }
        )


def test_redaction_does_not_change_delivered_pin():
    original = {"dt": [{"pin": "FIXTURE", "args": {"token": "FIXTURE"}}]}
    hidden = redact_rpc(original)
    assert hidden == {"dt": [{"pin": "***", "args": {"token": "***"}}]}
    assert original["dt"][0]["pin"] == "FIXTURE"


def test_unregistered_deployed_method_is_not_reinterpreted():
    task = TaskCreate(
        device_id=1, ext_task_id="fixture", method_code=7010, payload={"x": 1}
    )
    assert task.payload == {"x": 1}


@pytest.mark.anyio
@pytest.mark.parametrize("addressed", [False, True])
async def test_cancel_announcement_marks_payload_requirement(monkeypatch, addressed):
    from unittest.mock import AsyncMock
    from core.services import device_task_processing as transport
    from core.schemas.device_tasks import TaskResponse

    publisher = AsyncMock()
    monkeypatch.setattr(transport.topic_publisher, "publish", publisher)
    task = TaskCreate(
        device_id=1,
        ext_task_id="fixture",
        method_code=7002,
        payload={"dt": [{"session_id": str(uuid4())}] if addressed else []},
    )
    await transport.send_tsk("fixture", task, TaskResponse(id=uuid4(), created_at=1))
    arguments = publisher.call_args.kwargs
    assert arguments["message"].payload_required is addressed
    assert arguments["headers"]["payload_required"] == ("1" if addressed else "0")


@pytest.mark.anyio
async def test_cancel_dispatch_retains_terminal_eof():
    from unittest.mock import AsyncMock
    from core.diagnostics.schemas import (
        CancelDiagnosticMessage,
        DeviceOutputEnvelope,
        ExecDiagnosticMessage,
    )
    from core.diagnostics.service import DiagnosticService
    from core.diagnostics.sessions import DiagnosticsSessionRegistry

    registry = DiagnosticsSessionRegistry()
    service = DiagnosticService(registry, AsyncMock())
    session = await service.exec("fixture", ExecDiagnosticMessage(command_id="time"))
    assert await service.cancel(
        "fixture", CancelDiagnosticMessage(session_id=session.session_id)
    )
    assert await registry.route_output(
        "fixture",
        DeviceOutputEnvelope(
            session_id=session.session_id, seq=1, eof=True, exit_code=130
        ),
    )
    await session.queue.get()  # initial started status
    final = await session.queue.get()
    assert final.eof and final.exit_code == 130


@pytest.mark.anyio
async def test_closing_forwarder_expires_without_terminal_eof():
    from datetime import UTC, datetime, timedelta
    from unittest.mock import AsyncMock

    from api.internal_v1.diagnostics import _forward_session_queue
    from core.diagnostics.schemas import DiagnosticSessionKind
    from core.diagnostics.sessions import DiagnosticSession

    session = DiagnosticSession(
        sn="fixture",
        session_id=uuid4(),
        kind=DiagnosticSessionKind.EXEC,
        ttl_sec=1,
        closing=True,
        created_at=datetime.now(UTC) - timedelta(seconds=2),
    )
    socket = AsyncMock()
    await _forward_session_queue(socket, session)
    assert socket.send_json.call_args.args[0]["error"] == "session_expired"
