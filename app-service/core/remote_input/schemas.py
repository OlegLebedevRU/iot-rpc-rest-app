from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

NackCode = Literal[
    "interactive_desktop_unavailable",
    "lease_invalid",
    "expired",
    "duplicate",
    "invalid_sn",
    "invalid_payload",
    "unsupported",
    "inject_failed",
]


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── Server → Terminal Commands ───────────────────────────────────────────────


class PointerMoveCommand(StrictBaseModel):
    v: Literal[1] = 1
    type: Literal["pointer_move"] = "pointer_move"
    command_id: UUID
    lease_id: UUID
    sn: str
    x: int = Field(..., ge=0, le=65535)
    y: int = Field(..., ge=0, le=65535)
    issued_at_ms: int
    expires_at_ms: int


class MouseClickCommand(StrictBaseModel):
    v: Literal[1] = 1
    type: Literal["mouse_click"] = "mouse_click"
    command_id: UUID
    lease_id: UUID
    sn: str
    x: int = Field(..., ge=0, le=65535)
    y: int = Field(..., ge=0, le=65535)
    button: Literal["left"] = "left"
    issued_at_ms: int
    expires_at_ms: int


# ── Terminal → Server Inbound Envelopes ──────────────────────────────────────


class ScreenInfo(StrictBaseModel):
    virtual_x: int = 0
    virtual_y: int = 0
    virtual_width: int
    virtual_height: int


class CtlAck(StrictBaseModel):
    v: Literal[1] = 1
    type: Literal["ack"] = "ack"
    command_id: UUID
    lease_id: UUID
    sn: str
    result: Literal["injected"] = "injected"
    terminal_time_ms: int | None = None


class CtlNack(StrictBaseModel):
    v: Literal[1] = 1
    type: Literal["nack"] = "nack"
    command_id: UUID
    lease_id: UUID
    sn: str
    code: NackCode
    message: str
    terminal_time_ms: int | None = None


class CtlPresence(StrictBaseModel):
    v: Literal[1] = 1
    type: Literal["presence"] = "presence"
    agent: Literal["l4desk"] = "l4desk"
    status: Literal["online", "offline"]
    desktop_available: bool = False
    screen: ScreenInfo | None = None
    timestamp: str


CtlInboundMessage = Annotated[
    Union[CtlAck, CtlNack, CtlPresence],
    Field(discriminator="type"),
]

CtlInboundAdapter: TypeAdapter[CtlInboundMessage] = TypeAdapter(CtlInboundMessage)


# ── REST DTOs ────────────────────────────────────────────────────────────────


class AgentStatusView(BaseModel):
    online: bool
    desktop_available: bool
    screen: ScreenInfo | None = None
    last_seen_at: str | None = None
    stale: bool


class LeaseStatusView(BaseModel):
    active: bool
    lease_id: UUID | None = None
    owner_user_id: str | None = None
    expires_at: str | None = None


class StatusResponse(BaseModel):
    sn: str
    agent: AgentStatusView
    lease: LeaseStatusView


class LeaseRequest(StrictBaseModel):
    owner_user_id: str | None = None
    owner_role: str | None = None


class LeaseResponse(BaseModel):
    lease_id: UUID
    sn: str
    device_id: int
    org_id: int
    owner_user_id: str
    created_at: datetime
    expires_at: datetime
    keepalive_sec: int
    ws_path: str


class MoveRequest(StrictBaseModel):
    x: int = Field(..., ge=0, le=65535)
    y: int = Field(..., ge=0, le=65535)


class ClickRequest(StrictBaseModel):
    x: int = Field(..., ge=0, le=65535)
    y: int = Field(..., ge=0, le=65535)
    button: Literal["left"] = "left"
    client_ref: str | None = Field(default=None, max_length=64)


class ClickResult(BaseModel):
    command_id: UUID
    client_ref: str | None = None
    result: Literal["injected", "nack", "unconfirmed"]
    code: str | None = None
    message: str | None = None
    latency_ms: int | None = None


# ── WebSocket DTOs ───────────────────────────────────────────────────────────


class WsPointerMove(StrictBaseModel):
    type: Literal["pointer_move"] = "pointer_move"
    x: int = Field(..., ge=0, le=65535)
    y: int = Field(..., ge=0, le=65535)


class WsMouseClick(StrictBaseModel):
    type: Literal["mouse_click"] = "mouse_click"
    x: int = Field(..., ge=0, le=65535)
    y: int = Field(..., ge=0, le=65535)
    button: Literal["left"] = "left"
    client_ref: str | None = Field(default=None, max_length=64)


class WsKeepalive(StrictBaseModel):
    type: Literal["keepalive"] = "keepalive"


class WsRelease(StrictBaseModel):
    type: Literal["release"] = "release"


WsInboundMessage = Annotated[
    Union[WsPointerMove, WsMouseClick, WsKeepalive, WsRelease],
    Field(discriminator="type"),
]

WsInboundAdapter: TypeAdapter[WsInboundMessage] = TypeAdapter(WsInboundMessage)


class WsLimits(BaseModel):
    move_per_sec: int
    click_per_sec: int


class WsHello(BaseModel):
    type: Literal["hello"] = "hello"
    lease_id: UUID
    sn: str
    expires_at: datetime
    keepalive_sec: int
    limits: WsLimits


class WsPresence(BaseModel):
    type: Literal["presence"] = "presence"
    online: bool
    desktop_available: bool
    screen: ScreenInfo | None = None
    last_seen_at: str | None = None
    stale: bool


class WsClickResult(BaseModel):
    type: Literal["click_result"] = "click_result"
    command_id: UUID
    client_ref: str | None = None
    result: Literal["injected", "nack", "unconfirmed"]
    code: str | None = None
    message: str | None = None
    latency_ms: int | None = None


class WsError(BaseModel):
    type: Literal["error"] = "error"
    code: Literal[
        "rate_limited", "invalid_message", "lease_inactive", "payload_too_large"
    ]
    message: str
    client_ref: str | None = None


class WsLeaseRevoked(BaseModel):
    type: Literal["lease_revoked"] = "lease_revoked"
    reason: Literal["expired", "released", "replaced", "server_shutdown"]
