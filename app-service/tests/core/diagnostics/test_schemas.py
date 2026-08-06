from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.diagnostics.commands import (
    CMD_DIAG_CANCEL,
    CMD_DIAG_EXEC,
    CMD_DIAG_STREAM_CONTROL,
)
from core.diagnostics.schemas import (
    BrowserMessageAdapter,
    DeviceOutputEnvelope,
    OutputEncoding,
    OutputKind,
    build_cancel_task,
    build_exec_task,
    build_start_log_task,
    build_stop_log_task,
)


def test_valid_device_output_envelope():
    session_id = uuid4()

    envelope = DeviceOutputEnvelope.model_validate(
        {
            "v": 1,
            "session_id": str(session_id),
            "seq": 42,
            "ts": "2026-08-05T12:34:56.789Z",
            "kind": "log",
            "stream": "esp32-log",
            "encoding": "utf-8",
            "data": "WiFi connected\n",
            "eof": False,
        }
    )

    assert envelope.session_id == session_id
    assert envelope.kind is OutputKind.LOG
    assert envelope.encoding is OutputEncoding.UTF8


@pytest.mark.parametrize(
    "payload",
    [
        {"seq": 1, "kind": "log", "stream": "stdout", "data": "x"},
        {
            "session_id": str(uuid4()),
            "seq": -1,
            "kind": "log",
            "stream": "stdout",
            "data": "x",
        },
        {
            "session_id": str(uuid4()),
            "seq": 1,
            "kind": "bad",
            "stream": "stdout",
            "data": "x",
        },
        {
            "session_id": str(uuid4()),
            "seq": 1,
            "kind": "log",
            "stream": "stdout",
            "encoding": "latin1",
            "data": "x",
        },
    ],
)
def test_invalid_device_output_envelope(payload):
    with pytest.raises(ValidationError):
        DeviceOutputEnvelope.model_validate(payload)


def test_base64_envelope_is_accepted_as_string_data():
    envelope = DeviceOutputEnvelope.model_validate(
        {
            "session_id": str(uuid4()),
            "seq": 43,
            "kind": "stdout",
            "stream": "stdout",
            "encoding": "base64",
            "data": "SGVsbG8NCg==",
        }
    )

    assert envelope.encoding is OutputEncoding.BASE64
    assert envelope.data == "SGVsbG8NCg=="


@pytest.mark.parametrize(
    "payload,expected_type",
    [
        ({"type": "start_log", "level": "debug", "ttl_sec": 300}, "start_log"),
        ({"type": "stop_log", "session_id": str(uuid4())}, "stop_log"),
        ({"type": "exec", "command_id": "system_info", "args": {}}, "exec"),
        (
            {"type": "cancel", "session_id": str(uuid4()), "reason": "browser_closed"},
            "cancel",
        ),
    ],
)
def test_browser_messages_validation(payload, expected_type):
    message = BrowserMessageAdapter.validate_python(payload)

    assert message.type == expected_type


def test_rpc_payload_builders():
    session_id = uuid4()

    start = build_start_log_task(session_id=session_id, sn="SN001", level="debug")
    stop = build_stop_log_task(session_id=session_id)
    exec_task = build_exec_task(
        session_id=session_id,
        sn="SN001",
        command_id="system_info",
        args={"verbose": True},
    )
    cancel = build_cancel_task(session_id=session_id, reason="browser_closed")

    assert start.method_code == CMD_DIAG_STREAM_CONTROL
    assert start.payload.dt[0].model_dump(mode="json", exclude_none=True) == {
        "action": "start",
        "session_id": str(session_id),
        "stream": "esp32-log",
        "level": "debug",
        "ttl_sec": 300,
        "max_rate_bps": 8192,
        "topic": "dev/SN001/out",
    }
    assert stop.method_code == CMD_DIAG_STREAM_CONTROL
    assert stop.payload.dt[0].model_dump(mode="json", exclude_none=True) == {
        "action": "stop",
        "session_id": str(session_id),
        "stream": "esp32-log",
    }
    assert exec_task.method_code == CMD_DIAG_EXEC
    assert exec_task.payload.dt[0].model_dump(mode="json") == {
        "session_id": str(session_id),
        "command_id": "system_info",
        "args": {"verbose": True},
        "ttl_sec": 60,
        "max_output_bytes": 1048576,
        "topic": "dev/SN001/out",
    }
    assert cancel.method_code == CMD_DIAG_CANCEL
    assert cancel.payload.dt[0].model_dump(mode="json", exclude_none=True) == {
        "session_id": str(session_id),
        "reason": "browser_closed",
    }
