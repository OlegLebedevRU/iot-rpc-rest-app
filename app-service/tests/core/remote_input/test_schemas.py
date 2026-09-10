from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from core.remote_input.schemas import (
    ALLOWED_VK_CODES,
    CtlAck,
    CtlInboundAdapter,
    CtlNack,
    CtlPresence,
    CtlStreamEvent,
    InventoryGetCommand,
    KeyEventCommand,
    MouseClickCommand,
    PointerMoveCommand,
    StreamStartCommand,
    StreamStopCommand,
    StreamInfo,
    WsInboundAdapter,
    WsKeyEvent,
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
        desktop_id="disp:1",
        stream_instance_id=uuid4(),
        issued_at_ms=1000,
        expires_at_ms=3000,
    )
    assert cmd.type == "pointer_move"
    assert cmd.x == 32768
    assert cmd.y == 16384
    assert cmd.desktop_id == "disp:1"


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
        desktop_id="disp:1",
        stream_instance_id=uuid4(),
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


def test_backward_compatibility_old_presence():
    # Legacy presence without session_id, inventory, stream
    raw = {
        "v": 1,
        "type": "presence",
        "agent": "l4desk",
        "status": "online",
        "desktop_available": True,
        "screen": {
            "virtual_x": 0,
            "virtual_y": 0,
            "virtual_width": 1920,
            "virtual_height": 1080,
        },
        "timestamp": "2026-09-09T00:00:00Z",
    }
    p = CtlInboundAdapter.validate_json(json.dumps(raw).encode("utf-8"))
    assert isinstance(p, CtlPresence)
    assert p.session_id is None
    assert p.inventory is None
    assert p.stream is None
    assert p.screen is not None
    assert p.screen.virtual_width == 1920


def test_backward_compatibility_old_ack():
    # Legacy ack without result or other new fields
    raw = {
        "v": 1,
        "type": "ack",
        "command_id": str(uuid4()),
        "lease_id": str(uuid4()),
        "sn": "SN_OLD",
    }
    ack = CtlInboundAdapter.validate_json(json.dumps(raw).encode("utf-8"))
    assert isinstance(ack, CtlAck)
    assert ack.result == "injected"
    assert ack.stream_instance_id is None
    assert ack.inventory is None


def test_new_presence_with_inventory_and_stream():
    stream_id = uuid4()
    raw = {
        "v": 1,
        "type": "presence",
        "agent": "l4desk",
        "status": "online",
        "desktop_available": True,
        "session_id": 1,
        "timestamp": "2026-09-09T12:00:00Z",
        "screen": {
            "virtual_x": 0,
            "virtual_y": 0,
            "virtual_width": 1920,
            "virtual_height": 1080,
        },
        "inventory": {
            "displays": [
                {
                    "desktop_id": "disp:hex1",
                    "name": r"\\.\DISPLAY1",
                    "primary": True,
                    "x": 0,
                    "y": 0,
                    "width": 1920,
                    "height": 1080,
                    "session_id": 1,
                    "policy": "input",
                }
            ],
            "cameras": [
                {
                    "camera_id": "cam:hex1",
                    "name": "USB Camera",
                    "available": True,
                }
            ],
        },
        "stream": {
            "state": "running",
            "mode": "desktop",
            "source_id": "disp:hex1",
            "stream_instance_id": str(stream_id),
            "profile": "default",
            "reason": None,
            "ffmpeg_pid": 1234,
            "started_at": "2026-09-09T12:00:00Z",
            "restart_count": 0,
        },
    }
    p = CtlInboundAdapter.validate_json(json.dumps(raw).encode("utf-8"))
    assert isinstance(p, CtlPresence)
    assert p.session_id == 1
    assert p.inventory is not None
    assert len(p.inventory.displays) == 1
    assert p.inventory.displays[0].policy == "input"
    assert len(p.inventory.cameras) == 1
    assert p.stream is not None
    assert p.stream.state == "running"
    assert p.stream.stream_instance_id == stream_id


def test_ctl_stream_event():
    sid = uuid4()
    raw = {
        "v": 1,
        "type": "stream_event",
        "stream_instance_id": str(sid),
        "state": "stopped",
        "reason": "normal_exit",
        "timestamp": "2026-09-09T12:05:00Z",
    }
    evt = CtlInboundAdapter.validate_json(json.dumps(raw).encode("utf-8"))
    assert isinstance(evt, CtlStreamEvent)
    assert evt.stream_instance_id == sid
    assert evt.state == "stopped"
    assert evt.reason == "normal_exit"


def test_new_server_commands():
    cid = uuid4()
    lid = uuid4()
    sid = uuid4()

    # 1. InventoryGetCommand
    inv_cmd = InventoryGetCommand(
        command_id=cid,
        lease_id=lid,
        sn="SN1",
        issued_at_ms=1000,
        expires_at_ms=6000,
    )
    assert inv_cmd.type == "inventory_get"

    # 2. StreamStartCommand
    start_cmd = StreamStartCommand(
        command_id=cid,
        lease_id=lid,
        sn="SN1",
        mode="desktop",
        source_id="disp:1",
        profile="default",
        stream_instance_id=sid,
        issued_at_ms=1000,
        expires_at_ms=16000,
    )
    assert start_cmd.type == "stream_start"
    assert start_cmd.stream_instance_id == sid

    # 3. StreamStopCommand
    stop_cmd = StreamStopCommand(
        command_id=cid,
        lease_id=lid,
        sn="SN1",
        stream_instance_id=sid,
        issued_at_ms=1000,
        expires_at_ms=6000,
    )
    assert stop_cmd.type == "stream_stop"

    # 4. KeyEventCommand
    key_cmd = KeyEventCommand(
        command_id=cid,
        lease_id=lid,
        sn="SN1",
        desktop_id="disp:1",
        stream_instance_id=sid,
        kind="down",
        vk=0x0D,
        text="Enter",
        issued_at_ms=1000,
        expires_at_ms=6000,
    )
    assert key_cmd.type == "key_event"
    assert key_cmd.vk == 0x0D


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
            code="totally_unknown_code",  # type: ignore[arg-type]
            message="Error",
        )


def test_vk_whitelist():
    assert 0x08 in ALLOWED_VK_CODES  # Backspace
    assert 0x09 in ALLOWED_VK_CODES  # Tab
    assert 0x0D in ALLOWED_VK_CODES  # Enter
    assert 0x1B in ALLOWED_VK_CODES  # Esc
    assert 0x20 in ALLOWED_VK_CODES  # Space
    assert 0x2E in ALLOWED_VK_CODES  # Delete
    assert 0x25 in ALLOWED_VK_CODES  # Left arrow
    assert 0x28 in ALLOWED_VK_CODES  # Down arrow
    assert 0x30 in ALLOWED_VK_CODES  # '0'
    assert 0x39 in ALLOWED_VK_CODES  # '9'
    assert 0x41 in ALLOWED_VK_CODES  # 'A'
    assert 0x5A in ALLOWED_VK_CODES  # 'Z'
    assert 0x70 in ALLOWED_VK_CODES  # F1
    assert 0x7B in ALLOWED_VK_CODES  # F12
    assert 0xFF not in ALLOWED_VK_CODES


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

    key_json = json.dumps(
        {"type": "key_event", "kind": "press", "vk": 0x0D, "text": "Enter"}
    )
    parsed_key = WsInboundAdapter.validate_json(key_json.encode("utf-8"))
    assert isinstance(parsed_key, WsKeyEvent)
    assert parsed_key.vk == 0x0D

    # Unsupported type
    with pytest.raises(ValidationError):
        WsInboundAdapter.validate_json(b'{"type": "invalid_type"}')


def test_ctl_ack_with_nack_result_compatibility():
    # Terminal l4desk sends nack as type="ack", result="nack"
    raw = {
        "v": 1,
        "type": "ack",
        "command_id": str(uuid4()),
        "lease_id": str(uuid4()),
        "sn": "a4b0000773c82116d210826",
        "result": "nack",
        "code": "unsupported",
        "message": "Unsupported command type",
        "terminal_time_ms": 1726000000000,
    }
    ack = CtlInboundAdapter.validate_json(json.dumps(raw).encode("utf-8"))
    assert isinstance(ack, CtlAck)
    assert ack.result == "nack"
    assert ack.code == "unsupported"
    assert ack.message == "Unsupported command type"


def test_ctl_ack_with_inventory_result():
    raw = {
        "v": 1,
        "type": "ack",
        "command_id": str(uuid4()),
        "lease_id": str(uuid4()),
        "sn": "a4b0000773c82116d210826",
        "result": "inventory",
        "inventory": {
            "displays": [
                {
                    "desktop_id": "0",
                    "name": "Screen 1",
                    "primary": True,
                    "x": 0,
                    "y": 0,
                    "width": 1920,
                    "height": 1080,
                }
            ],
            "cameras": [],
        },
    }
    ack = CtlInboundAdapter.validate_json(json.dumps(raw).encode("utf-8"))
    assert isinstance(ack, CtlAck)
    assert ack.result == "inventory"
    assert ack.inventory is not None
    assert len(ack.inventory.displays) == 1


def test_stream_info_flexibility_empty_values_and_int_timestamp():
    # Empty mode and empty stream_instance_id, integer started_at
    info = StreamInfo(
        state="stopped",
        mode="",
        stream_instance_id="",
        started_at=1726000000,
    )
    assert info.mode == ""
    assert info.stream_instance_id == ""
    assert info.started_at == 1726000000

    # Also test parsing from JSON / presence with empty strings and int started_at
    raw_presence = {
        "v": 1,
        "type": "presence",
        "status": "online",
        "desktop_available": True,
        "timestamp": "2026-09-10T12:00:00Z",
        "stream": {
            "state": "stopped",
            "mode": "",
            "source_id": None,
            "stream_instance_id": "",
            "profile": "default",
            "reason": None,
            "ffmpeg_pid": None,
            "started_at": 1726000000,
            "restart_count": 0,
        },
    }
    presence = CtlInboundAdapter.validate_json(json.dumps(raw_presence).encode("utf-8"))
    assert isinstance(presence, CtlPresence)
    assert presence.stream is not None
    assert presence.stream.mode == ""
    assert presence.stream.stream_instance_id == ""
    assert presence.stream.started_at == 1726000000

    # Test with string started_at
    info_str = StreamInfo(started_at="2026-09-10T12:00:00Z")
    assert info_str.started_at == "2026-09-10T12:00:00Z"


def test_ctl_ack_tolerance_to_empty_stream_instance_id():
    cid = uuid4()
    lid = uuid4()
    raw = {
        "v": 1,
        "type": "ack",
        "command_id": str(cid),
        "lease_id": str(lid),
        "sn": "SN123",
        "result": "stopped",
        "stream_instance_id": "",
    }
    # Direct model instantiation with empty string
    ack = CtlAck(**raw)
    assert ack.stream_instance_id is None

    # Via CtlInboundAdapter (JSON bytes)
    parsed = CtlInboundAdapter.validate_json(json.dumps(raw).encode("utf-8"))
    assert isinstance(parsed, CtlAck)
    assert parsed.stream_instance_id is None

    # Via CtlInboundAdapter (Python dict)
    parsed_dict = CtlInboundAdapter.validate_python(raw)
    assert isinstance(parsed_dict, CtlAck)
    assert parsed_dict.stream_instance_id is None

    # Valid UUID string remains parsed as UUID
    valid_uuid_str = "e2d83e20-3ca2-4ff5-b9aa-78d15ba40939"
    raw["stream_instance_id"] = valid_uuid_str
    ack_valid = CtlAck(**raw)
    assert ack_valid.stream_instance_id == UUID(valid_uuid_str)
