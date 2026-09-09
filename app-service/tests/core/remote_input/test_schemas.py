from __future__ import annotations

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.remote_input.schemas import (
    CtlAck,
    CtlInboundAdapter,
    CtlNack,
    CtlPresence,
    MouseClickCommand,
    PointerMoveCommand,
    ScreenInfo,
    WsInboundAdapter,
    WsMouseClick,
    WsPointerMove,
)


def test_pointer_move_command_valid():
    cmd = PointerMoveCommand(
        command_id=uuid4(),
        lease_id=uuid4(),
        sn="SN12345",
        x=32768,
        y=16384,
        issued_at_ms=1000,
        expires_at_ms=3000,
    )
    assert cmd.type == "pointer_move"
    assert cmd.x == 32768
    assert cmd.y == 16384


def test_pointer_move_command_invalid_coords_and_extra():
    # Negative coord
    with pytest.raises(ValidationError):
        PointerMoveCommand(
            command_id=uuid4(),
            lease_id=uuid4(),
            sn="SN12345",
            x=-1,
            y=100,
            issued_at_ms=1000,
            expires_at_ms=3000,
        )

    # Exceeding 65535
    with pytest.raises(ValidationError):
        PointerMoveCommand(
            command_id=uuid4(),
            lease_id=uuid4(),
            sn="SN12345",
            x=100,
            y=65536,
            issued_at_ms=1000,
            expires_at_ms=3000,
        )

    # Extra field forbidden
    with pytest.raises(ValidationError):
        PointerMoveCommand.model_validate(
            {
                "command_id": str(uuid4()),
                "lease_id": str(uuid4()),
                "sn": "SN12345",
                "x": 100,
                "y": 100,
                "issued_at_ms": 1000,
                "expires_at_ms": 3000,
                "extra_field": "disallowed",
            }
        )


def test_mouse_click_command_valid():
    cmd = MouseClickCommand(
        command_id=uuid4(),
        lease_id=uuid4(),
        sn="SN12345",
        x=0,
        y=65535,
        button="left",
        issued_at_ms=1000,
        expires_at_ms=6000,
    )
    assert cmd.button == "left"


def test_mouse_click_invalid_button():
    with pytest.raises(ValidationError):
        MouseClickCommand(
            command_id=uuid4(),
            lease_id=uuid4(),
            sn="SN12345",
            x=0,
            y=0,
            button="right",  # Only left supported in alpha
            issued_at_ms=1000,
            expires_at_ms=6000,
        )


def test_ctl_ack_and_adapter():
    cid = uuid4()
    lid = uuid4()
    data = {
        "v": 1,
        "type": "ack",
        "command_id": str(cid),
        "lease_id": str(lid),
        "sn": "SN123",
        "result": "injected",
        "terminal_time_ms": 1788805978301,
    }
    msg = CtlInboundAdapter.validate_json(json.dumps(data).encode("utf-8"))
    assert isinstance(msg, CtlAck)
    assert msg.command_id == cid
    assert msg.result == "injected"


def test_ctl_nack_codes_and_validation():
    cid = uuid4()
    lid = uuid4()
    valid_codes = [
        "interactive_desktop_unavailable",
        "lease_invalid",
        "expired",
        "duplicate",
        "invalid_sn",
        "invalid_payload",
        "unsupported",
        "inject_failed",
    ]
    for code in valid_codes:
        nack = CtlNack(
            command_id=cid,
            lease_id=lid,
            sn="SN123",
            code=code,
            message="Error occurred",
        )
        assert nack.code == code

    with pytest.raises(ValidationError):
        CtlNack(
            command_id=cid,
            lease_id=lid,
            sn="SN123",
            code="unknown_code",  # type: ignore[arg-type]
            message="Error",
        )


def test_ctl_presence_validation():
    presence = CtlPresence(
        agent="l4desk",
        status="online",
        desktop_available=True,
        screen=ScreenInfo(
            virtual_x=0,
            virtual_y=0,
            virtual_width=1920,
            virtual_height=1080,
        ),
        timestamp="2026-09-09T00:00:00Z",
    )
    assert presence.screen.virtual_width == 1920

    # Extra fields forbidden
    with pytest.raises(ValidationError):
        CtlPresence.model_validate(
            {
                "agent": "l4desk",
                "status": "online",
                "desktop_available": True,
                "timestamp": "2026-09-09T00:00:00Z",
                "extra": 123,
            }
        )


def test_ws_inbound_adapter():
    move_json = json.dumps({"type": "pointer_move", "x": 100, "y": 200})
    parsed_move = WsInboundAdapter.validate_json(move_json.encode("utf-8"))
    assert isinstance(parsed_move, WsPointerMove)
    assert parsed_move.x == 100

    click_json = json.dumps(
        {"type": "mouse_click", "x": 10, "y": 20, "button": "left", "client_ref": "c-1"}
    )
    parsed_click = WsInboundAdapter.validate_json(click_json.encode("utf-8"))
    assert isinstance(parsed_click, WsMouseClick)
    assert parsed_click.client_ref == "c-1"

    # Unsupported type
    with pytest.raises(ValidationError):
        WsInboundAdapter.validate_json(b'{"type": "invalid_type"}')
