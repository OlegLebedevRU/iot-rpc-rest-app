from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from core.diagnostics.commands import (
    CMD_DIAG_CANCEL,
    CMD_DIAG_EXEC,
    CMD_DIAG_STREAM_CONTROL,
    DEFAULT_DIAG_EXEC_TTL_SEC,
    DEFAULT_LIVE_LOG_TTL_SEC,
    DEFAULT_MAX_OUTPUT_BYTES,
    DEFAULT_MAX_RATE_BPS,
)


class OutputKind(StrEnum):
    LOG = "log"
    STDOUT = "stdout"
    STDERR = "stderr"
    STATUS = "status"
    RESULT = "result"
    ERROR = "error"


class OutputEncoding(StrEnum):
    UTF8 = "utf-8"
    BASE64 = "base64"


class DiagnosticSessionKind(StrEnum):
    LIVE_LOG = "live_log"
    EXEC = "exec"


class DeviceOutputEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    v: int = Field(default=1, ge=1)
    session_id: UUID | str
    seq: int = Field(ge=0)
    ts: str | None = None
    kind: OutputKind = OutputKind.STDOUT
    stream: str = Field(default="stdout", min_length=1, max_length=64)
    encoding: OutputEncoding = OutputEncoding.UTF8
    data: str = ""
    eof: bool = False
    exit_code: int | None = None
    truncated: bool = False

    @field_validator("session_id", mode="before")
    @classmethod
    def _parse_session_id(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return UUID(v)
            except (ValueError, TypeError):
                return v
        return v

    @model_validator(mode="before")
    @classmethod
    def _adapt_contract_v1(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            stream = data.get("stream")
            eof = data.get("eof", False)
            if "kind" not in data or data["kind"] is None:
                if eof and data.get("exit_code") is not None:
                    data["kind"] = OutputKind.RESULT
                elif stream == "stderr":
                    data["kind"] = OutputKind.STDERR
                else:
                    data["kind"] = OutputKind.STDOUT
            if "stream" not in data or not data["stream"]:
                if data.get("kind") == OutputKind.STDERR:
                    data["stream"] = "stderr"
                else:
                    data["stream"] = "stdout"
            if "data" not in data or data["data"] is None:
                data["data"] = ""
        return data


class BrowserMessageType(StrEnum):
    START_LOG = "start_log"
    STOP_LOG = "stop_log"
    EXEC = "exec"
    CANCEL = "cancel"


class BrowserBaseMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: BrowserMessageType


class StartLogMessage(BrowserBaseMessage):
    type: Literal[BrowserMessageType.START_LOG] = BrowserMessageType.START_LOG
    level: str = Field(default="info", min_length=1, max_length=16)
    stream: str = Field(default="esp32-log", min_length=1, max_length=64)
    ttl_sec: int = Field(default=DEFAULT_LIVE_LOG_TTL_SEC, ge=1, le=3600)
    max_rate_bps: int = Field(default=DEFAULT_MAX_RATE_BPS, ge=1, le=1_048_576)


class StopLogMessage(BrowserBaseMessage):
    type: Literal[BrowserMessageType.STOP_LOG] = BrowserMessageType.STOP_LOG
    session_id: UUID | str
    stream: str = Field(default="esp32-log", min_length=1, max_length=64)


class ExecDiagnosticMessage(BrowserBaseMessage):
    type: Literal[BrowserMessageType.EXEC] = BrowserMessageType.EXEC
    command_id: str = Field(default="raw_cmd", min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.:-]+$")
    command_line: str | None = Field(default=None, max_length=4096)
    shell: str | None = Field(default="cmd", max_length=32)
    session_id: UUID | str | None = Field(default=None)
    sn: str | None = Field(default=None, max_length=64)
    args: dict[str, Any] = Field(default_factory=dict)
    ttl_sec: int = Field(default=DEFAULT_DIAG_EXEC_TTL_SEC, ge=1, le=3600)
    max_output_bytes: int = Field(default=DEFAULT_MAX_OUTPUT_BYTES, ge=1)


class CancelDiagnosticMessage(BrowserBaseMessage):
    type: Literal[BrowserMessageType.CANCEL] = BrowserMessageType.CANCEL
    session_id: UUID | str
    sn: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=128)


BrowserMessage = Annotated[
    StartLogMessage | StopLogMessage | ExecDiagnosticMessage | CancelDiagnosticMessage,
    Field(discriminator="type"),
]
BrowserMessageAdapter = TypeAdapter(BrowserMessage)


class StreamControlAction(StrEnum):
    START = "start"
    STOP = "stop"


class DiagStreamControlPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: StreamControlAction
    session_id: UUID | str
    stream: str = Field(default="esp32-log", min_length=1, max_length=64)
    level: str | None = Field(default=None, min_length=1, max_length=16)
    ttl_sec: int | None = Field(default=None, ge=1, le=3600)
    max_rate_bps: int | None = Field(default=None, ge=1, le=1_048_576)
    topic: str | None = None


class DiagExecPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: UUID | str
    command_id: str = Field(default="raw_cmd", min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.:-]+$")
    command_line: str | None = None
    shell: str | None = "cmd"
    args: dict[str, Any] = Field(default_factory=dict)
    ttl_sec: int = Field(default=DEFAULT_DIAG_EXEC_TTL_SEC, ge=1, le=3600)
    max_output_bytes: int = Field(default=DEFAULT_MAX_OUTPUT_BYTES, ge=1)
    topic: str | None = None


class DiagCancelPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID | str
    reason: str | None = Field(default=None, max_length=128)


class DiagnosticRpcPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dt: list[DiagStreamControlPayload | DiagExecPayload | DiagCancelPayload]


class DiagnosticRpcTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method_code: int
    payload: DiagnosticRpcPayload


class BackendMessageType(StrEnum):
    OUTPUT = "output"
    STATUS = "status"
    ERROR = "error"


class BackendOutputMessage(BaseModel):
    type: Literal[BackendMessageType.OUTPUT] = BackendMessageType.OUTPUT
    sn: str
    session_id: UUID | str
    seq: int
    ts: str | None = None
    kind: OutputKind
    stream: str
    encoding: OutputEncoding
    data: str
    eof: bool = False
    exit_code: int | None = None
    truncated: bool = False


class BackendStatusMessage(BaseModel):
    type: Literal[BackendMessageType.STATUS] = BackendMessageType.STATUS
    session_id: UUID | str
    status: str


class BackendErrorMessage(BaseModel):
    type: Literal[BackendMessageType.ERROR] = BackendMessageType.ERROR
    session_id: UUID | str | None = None
    error: str


BackendMessage = BackendOutputMessage | BackendStatusMessage | BackendErrorMessage


def output_to_backend_message(
    sn: str, envelope: DeviceOutputEnvelope
) -> BackendOutputMessage:
    return BackendOutputMessage(
        sn=sn,
        session_id=envelope.session_id,
        seq=envelope.seq,
        ts=envelope.ts,
        kind=envelope.kind,
        stream=envelope.stream,
        encoding=envelope.encoding,
        data=envelope.data,
        eof=envelope.eof,
        exit_code=envelope.exit_code,
        truncated=envelope.truncated,
    )


def build_start_log_task(
    *,
    session_id: UUID,
    sn: str,
    level: str = "info",
    stream: str = "esp32-log",
    ttl_sec: int = DEFAULT_LIVE_LOG_TTL_SEC,
    max_rate_bps: int = DEFAULT_MAX_RATE_BPS,
) -> DiagnosticRpcTask:
    return DiagnosticRpcTask(
        method_code=CMD_DIAG_STREAM_CONTROL,
        payload=DiagnosticRpcPayload(
            dt=[
                DiagStreamControlPayload(
                    action=StreamControlAction.START,
                    session_id=session_id,
                    stream=stream,
                    level=level,
                    ttl_sec=ttl_sec,
                    max_rate_bps=max_rate_bps,
                    topic=f"dev/{sn}/out",
                )
            ]
        ),
    )


def build_stop_log_task(
    *,
    session_id: UUID,
    stream: str = "esp32-log",
) -> DiagnosticRpcTask:
    return DiagnosticRpcTask(
        method_code=CMD_DIAG_STREAM_CONTROL,
        payload=DiagnosticRpcPayload(
            dt=[
                DiagStreamControlPayload(
                    action=StreamControlAction.STOP,
                    session_id=session_id,
                    stream=stream,
                )
            ]
        ),
    )


def build_exec_task(
    *,
    session_id: UUID,
    sn: str | None = None,
    command_id: str = "raw_cmd",
    command_line: str | None = None,
    shell: str | None = "cmd",
    args: dict[str, Any] | None = None,
    ttl_sec: int = DEFAULT_DIAG_EXEC_TTL_SEC,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    topic: str | None = None,
) -> DiagnosticRpcTask:
    topic_value = topic or (f"dev/{sn}/out" if sn else None)
    return DiagnosticRpcTask(
        method_code=CMD_DIAG_EXEC,
        payload=DiagnosticRpcPayload(
            dt=[
                DiagExecPayload(
                    session_id=session_id,
                    command_id=command_id,
                    command_line=command_line,
                    shell=shell,
                    args=args or {},
                    ttl_sec=ttl_sec,
                    max_output_bytes=max_output_bytes,
                    topic=topic_value,
                )
            ]
        ),
    )


def build_cancel_task(
    *,
    session_id: UUID,
    reason: str | None = None,
) -> DiagnosticRpcTask:
    return DiagnosticRpcTask(
        method_code=CMD_DIAG_CANCEL,
        payload=DiagnosticRpcPayload(
            dt=[DiagCancelPayload(session_id=session_id, reason=reason)]
        ),
    )
