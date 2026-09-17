from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RemoteSessionEventType(StrEnum):
    DEVICE_ONLINE = "device_online"
    REMOTE_SESSION_START_REQUESTED = "remote_session_start_requested"
    REMOTE_SESSION_ACTIVE = "remote_session_active"
    REMOTE_SESSION_STOP_REQUESTED = "remote_session_stop_requested"
    REMOTE_SESSION_CLOSED = "remote_session_closed"
    REMOTE_SESSION_FAILED = "remote_session_failed"
    CONSOLE_COMMAND_STARTED = "console_command_started"
    CONSOLE_COMMAND_COMPLETED = "console_command_completed"
    CONSOLE_COMMAND_TIMED_OUT = "console_command_timed_out"


class RemoteSessionLifecycleState(StrEnum):
    REQUESTED = "requested"
    ACTIVE = "active"
    STOPPING = "stopping"
    CLOSED = "closed"
    FAILED = "failed"


class RemoteSessionType(StrEnum):
    CONSOLE = "console"
    VIDEO = "video"


FORBIDDEN_EVENT_COMMERCIAL_FIELDS: frozenset[str] = frozenset([
    "billing",
    "price",
    "tariff",
    "cost",
    "payment",
    "fee",
    "amount",
    "currency",
    "invoice",
    "balance",
    "account",
    "subscription",
    "entitlement",
    "kopeck",
    "ruble",
    "rub",
    "subledger",
])


def validate_no_commercial_fields(data: Any, path: str = "") -> None:
    """Recursively ensure no commercial or billing terms appear in IoT event payload."""
    if isinstance(data, dict):
        for key, value in data.items():
            key_lower = str(key).lower()
            if any(forbidden in key_lower for forbidden in FORBIDDEN_EVENT_COMMERCIAL_FIELDS):
                raise ValueError(
                    f"Commercial or billing field '{key}' detected at '{path}'. "
                    "Financial semantics are strictly forbidden in IoT event feed."
                )
            validate_no_commercial_fields(value, f"{path}.{key}" if path else str(key))
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            validate_no_commercial_fields(item, f"{path}[{idx}]")


class RemoteSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(..., description="UUID for idempotency")
    contract_version: str = Field("1.0.0", description="Contract version")
    tenant_id: int = Field(..., description="Tenant / Organization ID")
    terminal_id: str | None = Field(None, description="Terminal identifier")
    sn: str = Field(..., min_length=1, description="Device serial number")
    session_type: RemoteSessionType = Field(..., description="console or video")
    requested_by_user_id: str | None = Field(None, description="Requesting user ID")
    correlation_id: str | None = Field(None, description="End-to-end correlation ID")
    session_metadata: dict[str, Any] = Field(default_factory=dict, description="Session attributes")

    @field_validator("operation_id")
    @classmethod
    def validate_operation_id(cls, v: str) -> str:
        val = str(v).strip()
        if not val:
            raise ValueError("operation_id cannot be empty")
        return val

    @field_validator("session_metadata")
    @classmethod
    def validate_metadata(cls, v: dict[str, Any]) -> dict[str, Any]:
        validate_no_commercial_fields(v)
        return v


class RemoteSessionStop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str | None = Field(None, description="UUID for idempotency")
    reason: str = Field("user_requested", description="Stop reason")
    correlation_id: str | None = Field(None, description="End-to-end correlation ID")


class RemoteSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    tenant_id: int
    terminal_id: str | None = None
    device_id: int | None = None
    sn: str
    session_type: str
    status: str
    requested_by_user_id: str | None = None
    operation_id: str | None = None
    correlation_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    closed_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    close_reason: str | None = None
    session_metadata: dict[str, Any] = Field(default_factory=dict)


class RemoteSessionEventItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cursor: int = Field(..., description="Monotonically increasing sequence cursor")
    event_id: str = Field(..., description="Unique event identifier")
    occurred_at: datetime = Field(..., description="UTC timestamp of occurrence")
    event_type: str = Field(..., description="Event type name")
    event_version: str = Field("1.0.0", description="Event contract version")
    tenant_id: int | None = Field(None, description="Tenant / Organization ID")
    terminal_id: str | None = Field(None, description="Terminal identifier")
    device_id: int | None = Field(None, description="Device internal ID")
    sn: str = Field(..., description="Device serial number")
    session_id: str | None = Field(None, description="Session ID if applicable")
    session_type: str | None = Field(None, description="console or video")
    lifecycle_state: str | None = Field(None, description="Lifecycle state of session")
    reason: str | None = Field(None, description="Reason or status code")
    operation_id: str | None = Field(None, description="Operation ID for idempotency")
    correlation_id: str | None = Field(None, description="End-to-end correlation ID")
    payload: dict[str, Any] = Field(default_factory=dict, description="Immutable event payload")
    created_at: datetime = Field(..., description="Database record creation timestamp")

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, v: dict[str, Any]) -> dict[str, Any]:
        validate_no_commercial_fields(v)
        return v


class RemoteSessionEventFeedResponse(BaseModel):
    items: list[RemoteSessionEventItem]
    next_cursor: int = Field(..., description="Cursor to use for subsequent 'after' query")
    has_more: bool = Field(..., description="Whether more events are available beyond this page")
    total_count: int = Field(..., description="Number of items returned in this page")
    server_time: datetime = Field(..., description="Current server UTC timestamp")


class RemoteSessionReconciliationResponse(BaseModel):
    tenant_id: int | None = None
    from_cursor: int | None = None
    to_cursor: int | None = None
    total_events: int = 0
    min_cursor: int | None = None
    max_cursor: int | None = None
    events_by_type: dict[str, int] = Field(default_factory=dict)
    active_sessions_count: int = 0
    sessions_by_status: dict[str, int] = Field(default_factory=dict)
    feed_sha256: str = Field(..., description="SHA-256 digest of feed facts for verification")
    server_time: datetime = Field(..., description="Current server UTC timestamp")
