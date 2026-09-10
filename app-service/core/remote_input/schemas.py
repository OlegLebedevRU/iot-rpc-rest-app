from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

NackCode = Literal[
    "interactive_desktop_unavailable",
    "lease_invalid",
    "expired",
    "duplicate",
    "invalid_sn",
    "invalid_payload",
    "unsupported",
    "inject_failed",
    "lease_mismatch",
    "desktop_mismatch",
    "stream_mismatch",
    "source_not_allowed",
    "source_unavailable",
    "session_unavailable",
    "busy_transition",
    "ffmpeg_missing",
    "ffmpeg_integrity",
    "input_not_allowed_in_camera_mode",
    "invalid_profile",
]

ALLOWED_VK_CODES: frozenset[int] = frozenset(
    [
        0x08,  # Backspace
        0x09,  # Tab
        0x0D,  # Enter
        0x1B,  # Esc
        0x20,  # Space
        0x2E,  # Delete
        *range(0x25, 0x28 + 1),  # Arrows: 0x25 Left, 0x26 Up, 0x27 Right, 0x28 Down
        *range(0x30, 0x39 + 1),  # 0-9
        *range(0x41, 0x5A + 1),  # A-Z
        *range(0x70, 0x7B + 1),  # F1-F12
    ]
)

LeaseScope = Literal["console", "view", "stream", "input"]

StreamState = Literal[
    "stopped",
    "starting",
    "running",
    "stopping",
    "restarting",
    "failed",
    "source_unavailable",
    "session_unavailable",
]

StreamMode = Literal["desktop", "usb-camera", "stopped"]

AckResult = Literal[
    "injected",
    "started",
    "already_running",
    "switched",
    "stopped",
    "already_stopped",
    "inventory",
    "nack",
]


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── Common Inventory & Stream Structures ─────────────────────────────────────


class ScreenInfo(StrictBaseModel):
    virtual_x: int = 0
    virtual_y: int = 0
    virtual_width: int
    virtual_height: int


class DisplayInfo(StrictBaseModel):
    desktop_id: str
    name: str
    primary: bool = False
    x: int = 0
    y: int = 0
    width: int
    height: int
    session_id: int | None = None
    policy: Literal["input", "view", "denied"] = "input"


class CameraInfo(StrictBaseModel):
    camera_id: str
    name: str
    available: bool = True


class InventoryInfo(StrictBaseModel):
    displays: list[DisplayInfo] = Field(default_factory=list)
    cameras: list[CameraInfo] = Field(default_factory=list)


class StreamInfo(StrictBaseModel):
    state: StreamState = "stopped"
    mode: StreamMode | Literal[""] = "stopped"
    source_id: str | None = None
    stream_instance_id: UUID | Literal[""] | None = None
    profile: str = "default"
    reason: str | None = None
    ffmpeg_pid: int | None = None
    started_at: str | int | None = None
    restart_count: int = 0


# ── Server → Terminal Commands ───────────────────────────────────────────────


class PointerMoveCommand(StrictBaseModel):
    v: Literal[1] = 1
    type: Literal["pointer_move"] = "pointer_move"
    command_id: UUID
    lease_id: UUID
    sn: str
    x: int = Field(..., ge=0, le=65535)
    y: int = Field(..., ge=0, le=65535)
    desktop_id: str | None = None
    stream_instance_id: UUID | None = None
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
    desktop_id: str | None = None
    stream_instance_id: UUID | None = None
    issued_at_ms: int
    expires_at_ms: int


class InventoryGetCommand(StrictBaseModel):
    v: Literal[1] = 1
    type: Literal["inventory_get"] = "inventory_get"
    command_id: UUID
    lease_id: UUID | None = None
    sn: str
    issued_at_ms: int
    expires_at_ms: int


class StreamStartCommand(StrictBaseModel):
    v: Literal[1] = 1
    type: Literal["stream_start"] = "stream_start"
    command_id: UUID
    lease_id: UUID
    sn: str
    mode: Literal["desktop", "usb-camera"]
    source_id: str
    profile: str = "default"
    stream_instance_id: UUID
    issued_at_ms: int
    expires_at_ms: int


class StreamStopCommand(StrictBaseModel):
    v: Literal[1] = 1
    type: Literal["stream_stop"] = "stream_stop"
    command_id: UUID
    lease_id: UUID
    sn: str
    stream_instance_id: UUID | None = None
    issued_at_ms: int
    expires_at_ms: int


class KeyEventCommand(StrictBaseModel):
    v: Literal[1] = 1
    type: Literal["key_event"] = "key_event"
    command_id: UUID
    lease_id: UUID
    sn: str
    desktop_id: str | None = None
    stream_instance_id: UUID | None = None
    kind: Literal["down", "up", "press"]
    vk: int = Field(..., ge=0, le=255)
    text: str | None = Field(default=None, max_length=32)
    issued_at_ms: int
    expires_at_ms: int


# ── Terminal → Server Inbound Envelopes ──────────────────────────────────────


class CtlAck(StrictBaseModel):
    v: Literal[1] = 1
    type: Literal["ack"] = "ack"
    command_id: UUID
    lease_id: UUID | None = None
    sn: str
    result: AckResult = "injected"
    code: NackCode | str | None = None
    message: str | None = None
    terminal_time_ms: int | None = None
    stream_instance_id: UUID | None = None
    state: StreamState | None = None
    inventory: InventoryInfo | None = None

    @field_validator("stream_instance_id", mode="before")
    @classmethod
    def empty_stream_instance_id_to_none(cls, v: Any) -> Any:
        if v == "" or (isinstance(v, str) and not v.strip()):
            return None
        return v


class CtlNack(StrictBaseModel):
    v: Literal[1] = 1
    type: Literal["nack"] = "nack"
    command_id: UUID
    lease_id: UUID | None = None
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
    session_id: int | None = None
    screen: ScreenInfo | None = None
    inventory: InventoryInfo | None = None
    stream: StreamInfo | None = None
    timestamp: str


class CtlStreamEvent(StrictBaseModel):
    v: Literal[1] = 1
    type: Literal["stream_event"] = "stream_event"
    sn: str | None = None
    stream_instance_id: UUID | None = None
    state: StreamState
    reason: str | None = None
    timestamp: str


CtlInboundMessage = Annotated[
    Union[CtlAck, CtlNack, CtlPresence, CtlStreamEvent],
    Field(discriminator="type"),
]

CtlInboundAdapter: TypeAdapter[CtlInboundMessage] = TypeAdapter(CtlInboundMessage)


# ── REST DTOs ────────────────────────────────────────────────────────────────


class AgentStatusView(BaseModel):
    online: bool
    desktop_available: bool
    session_id: int | None = None
    screen: ScreenInfo | None = None
    inventory: InventoryInfo | None = None
    stream: StreamInfo | None = None
    last_seen_at: str | None = None
    stale: bool


class LeaseStatusView(BaseModel):
    active: bool
    lease_id: UUID | None = None
    scope: LeaseScope | None = None
    owner_role: str | None = None
    owner_user_id: str | None = None
    owner_masked: str | None = None
    expires_at: str | None = None
    stream_instance_id: UUID | None = None
    selected_desktop_id: str | None = None


class StatusResponse(BaseModel):
    sn: str
    agent: AgentStatusView
    lease: LeaseStatusView


class LeaseRequest(StrictBaseModel):
    scope: LeaseScope = "input"
    ttl_sec: int | None = Field(default=None, ge=5, le=3600)
    owner_user_id: str | None = None
    owner_role: str | None = None


class LeaseResponse(BaseModel):
    lease_id: UUID
    sn: str
    device_id: int
    org_id: int
    owner_user_id: str
    owner_role: str
    scope: LeaseScope
    owner_session_id: str
    created_at: datetime
    expires_at: datetime
    keepalive_sec: int
    ws_path: str
    stream_instance_id: UUID | None = None
    selected_desktop_id: str | None = None
    selected_session_id: int | None = None
    stream_mode: str | None = None


class ScopeUpgradeRequest(StrictBaseModel):
    scope: LeaseScope


class DeleteByOwnerRequest(StrictBaseModel):
    user_id: str
    session_id: str | None = None


class StreamStartRequest(StrictBaseModel):
    mode: Literal["desktop", "usb-camera"]
    source_id: str
    profile: str = "default"


class StreamStartResponse(BaseModel):
    stream_instance_id: UUID
    result: str
    state: str | None = None


class StreamStopResponse(BaseModel):
    result: str


class MoveRequest(StrictBaseModel):
    x: int = Field(..., ge=0, le=65535)
    y: int = Field(..., ge=0, le=65535)
    desktop_id: str | None = None
    stream_instance_id: UUID | None = None


class ClickRequest(StrictBaseModel):
    x: int = Field(..., ge=0, le=65535)
    y: int = Field(..., ge=0, le=65535)
    button: Literal["left"] = "left"
    client_ref: str | None = Field(default=None, max_length=64)
    desktop_id: str | None = None
    stream_instance_id: UUID | None = None


class ClickResult(BaseModel):
    command_id: UUID
    client_ref: str | None = None
    result: Literal["injected", "nack", "unconfirmed"]
    code: str | None = None
    message: str | None = None
    latency_ms: int | None = None


class KeyRequest(StrictBaseModel):
    kind: Literal["down", "up", "press"]
    vk: int = Field(..., ge=0, le=255)
    text: str | None = Field(default=None, max_length=32)
    desktop_id: str | None = None
    stream_instance_id: UUID | None = None
    client_ref: str | None = Field(default=None, max_length=64)


class KeyResult(BaseModel):
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
    desktop_id: str | None = None
    stream_instance_id: UUID | None = None


class WsMouseClick(StrictBaseModel):
    type: Literal["mouse_click"] = "mouse_click"
    x: int = Field(..., ge=0, le=65535)
    y: int = Field(..., ge=0, le=65535)
    button: Literal["left"] = "left"
    client_ref: str | None = Field(default=None, max_length=64)
    desktop_id: str | None = None
    stream_instance_id: UUID | None = None


class WsKeyEvent(StrictBaseModel):
    type: Literal["key_event", "key"] = "key_event"
    kind: Literal["down", "up", "press"]
    vk: int = Field(..., ge=0, le=255)
    text: str | None = Field(default=None, max_length=32)
    desktop_id: str | None = None
    stream_instance_id: UUID | None = None
    client_ref: str | None = Field(default=None, max_length=64)


class WsKeepalive(StrictBaseModel):
    type: Literal["keepalive"] = "keepalive"


class WsRelease(StrictBaseModel):
    type: Literal["release"] = "release"


WsInboundMessage = Annotated[
    Union[WsPointerMove, WsMouseClick, WsKeyEvent, WsKeepalive, WsRelease],
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
    session_id: int | None = None
    screen: ScreenInfo | None = None
    inventory: InventoryInfo | None = None
    stream: StreamInfo | None = None
    last_seen_at: str | None = None
    stale: bool


class WsStreamState(BaseModel):
    type: Literal["stream_state"] = "stream_state"
    stream_instance_id: UUID | None = None
    state: StreamState
    reason: str | None = None
    timestamp: str | None = None


class WsClickResult(BaseModel):
    type: Literal["click_result"] = "click_result"
    command_id: UUID
    client_ref: str | None = None
    result: Literal["injected", "nack", "unconfirmed"]
    code: str | None = None
    message: str | None = None
    latency_ms: int | None = None


class WsKeyResult(BaseModel):
    type: Literal["key_result"] = "key_result"
    command_id: UUID
    client_ref: str | None = None
    result: Literal["injected", "nack", "unconfirmed"]
    code: str | None = None
    message: str | None = None
    latency_ms: int | None = None


class WsError(BaseModel):
    type: Literal["error"] = "error"
    code: (
        Literal[
            "rate_limited",
            "invalid_message",
            "lease_inactive",
            "payload_too_large",
            "scope_not_allowed",
            "input_not_allowed_in_camera_mode",
            "desktop_mismatch",
            "stream_mismatch",
            "vk_not_allowed",
        ]
        | str
    )
    message: str
    client_ref: str | None = None


class WsLeaseRevoked(BaseModel):
    type: Literal["lease_revoked"] = "lease_revoked"
    reason: str
