from __future__ import annotations

import json
from uuid import uuid4

import pytest

from core.remote_input.mqtt_bridge import (
    extract_sn_from_ctl_routing_key,
    handle_device_ctl_message,
)
from core.remote_input.pending import PendingCommandRegistry, PendingResult
from core.remote_input.presence import PresenceRegistry


def test_extract_sn_from_ctl_routing_key():
    assert extract_sn_from_ctl_routing_key("dev.SN12345.ctl") == "SN12345"
    assert extract_sn_from_ctl_routing_key("dev/SN12345/ctl") == "SN12345"
    assert extract_sn_from_ctl_routing_key("srv.SN12345.ctl") is None
    assert extract_sn_from_ctl_routing_key("dev.SN12345.evt") is None
    assert extract_sn_from_ctl_routing_key("dev.SN12345") is None


@pytest.mark.asyncio
async def test_handle_device_ctl_message_presence():
    p_reg = PresenceRegistry()
    cmd_reg = PendingCommandRegistry()

    payload = json.dumps(
        {
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
    ).encode("utf-8")

    res = await handle_device_ctl_message(
        routing_key="dev.SNTEST1.ctl",
        payload=payload,
        p_registry=p_reg,
        cmd_registry=cmd_reg,
    )
    assert res is True

    view = await p_reg.get("SNTEST1")
    assert view.online is True
    assert view.desktop_available is True
    assert view.screen.virtual_width == 1920


@pytest.mark.asyncio
async def test_handle_device_ctl_message_presence_with_inventory_and_stream():
    p_reg = PresenceRegistry()
    cmd_reg = PendingCommandRegistry()

    payload = json.dumps(
        {
            "v": 1,
            "type": "presence",
            "agent": "l4desk",
            "status": "online",
            "desktop_available": True,
            "session_id": 1,
            "timestamp": "2026-09-09T00:00:00Z",
            "inventory": {
                "displays": [
                    {
                        "desktop_id": "disp:1",
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
                        "camera_id": "cam:1",
                        "name": "USB Camera",
                        "available": True,
                    }
                ],
            },
            "stream": {
                "state": "running",
                "mode": "desktop",
                "source_id": "disp:1",
                "profile": "default",
                "restart_count": 0,
            },
        }
    ).encode("utf-8")

    res = await handle_device_ctl_message(
        routing_key="dev.SNTEST1.ctl",
        payload=payload,
        p_registry=p_reg,
        cmd_registry=cmd_reg,
    )
    assert res is True

    view = await p_reg.get("SNTEST1")
    assert view.online is True
    assert view.inventory is not None
    assert len(view.inventory.displays) == 1
    assert view.inventory.displays[0].desktop_id == "disp:1"
    assert view.stream is not None
    assert view.stream.state == "running"


@pytest.mark.asyncio
async def test_handle_device_ctl_message_stream_event():
    p_reg = PresenceRegistry()
    cmd_reg = PendingCommandRegistry()

    stream_id = uuid4()
    payload = json.dumps(
        {
            "v": 1,
            "type": "stream_event",
            "stream_instance_id": str(stream_id),
            "state": "running",
            "reason": None,
            "timestamp": "2026-09-09T00:00:05Z",
        }
    ).encode("utf-8")

    res = await handle_device_ctl_message(
        routing_key="dev.SNTEST1.ctl",
        payload=payload,
        p_registry=p_reg,
        cmd_registry=cmd_reg,
    )
    assert res is True

    stream_info = await p_reg.get_stream("SNTEST1")
    assert stream_info.state == "running"
    assert stream_info.stream_instance_id == stream_id


@pytest.mark.asyncio
async def test_handle_device_ctl_message_ack_resolves_pending():
    p_reg = PresenceRegistry()
    cmd_reg = PendingCommandRegistry()

    cid = uuid4()
    lid = uuid4()
    sn = "SNTEST1"

    fut = await cmd_reg.register(
        command_id=cid, lease_id=lid, sn=sn, cmd_type="mouse_click"
    )

    payload = json.dumps(
        {
            "v": 1,
            "type": "ack",
            "command_id": str(cid),
            "lease_id": str(lid),
            "sn": sn,
            "result": "injected",
            "terminal_time_ms": 123456,
        }
    ).encode("utf-8")

    handled = await handle_device_ctl_message(
        routing_key=f"dev.{sn}.ctl",
        payload=payload,
        p_registry=p_reg,
        cmd_registry=cmd_reg,
    )
    assert handled is True
    assert fut.done()
    res = fut.result()
    assert isinstance(res, PendingResult)
    assert res.result == "injected"
    assert res.terminal_time_ms == 123456

    # Duplicate ACK is ignored
    handled_dup = await handle_device_ctl_message(
        routing_key=f"dev.{sn}.ctl",
        payload=payload,
        p_registry=p_reg,
        cmd_registry=cmd_reg,
    )
    assert handled_dup is False


@pytest.mark.asyncio
async def test_handle_device_ctl_message_sn_mismatch_drop():
    p_reg = PresenceRegistry()
    cmd_reg = PendingCommandRegistry()

    cid = uuid4()
    lid = uuid4()

    # Topic has SN1, payload has SN2
    payload = json.dumps(
        {
            "v": 1,
            "type": "ack",
            "command_id": str(cid),
            "lease_id": str(lid),
            "sn": "SN2",
            "result": "injected",
        }
    ).encode("utf-8")

    handled = await handle_device_ctl_message(
        routing_key="dev.SN1.ctl",
        payload=payload,
        p_registry=p_reg,
        cmd_registry=cmd_reg,
    )
    assert handled is False


@pytest.mark.asyncio
async def test_handle_device_ctl_message_oversized_payload():
    p_reg = PresenceRegistry()
    cmd_reg = PendingCommandRegistry()

    # Max inbound payload is 65536 bytes
    oversized = b"{" + b"a" * 70000 + b"}"
    handled = await handle_device_ctl_message(
        routing_key="dev.SN1.ctl",
        payload=oversized,
        p_registry=p_reg,
        cmd_registry=cmd_reg,
    )
    assert handled is False


@pytest.mark.asyncio
async def test_handle_device_ctl_message_ack_nack_resolves_pending():
    p_reg = PresenceRegistry()
    cmd_reg = PendingCommandRegistry()

    cid = uuid4()
    lid = uuid4()
    sn = "SNTEST1"

    fut = await cmd_reg.register(
        command_id=cid, lease_id=lid, sn=sn, cmd_type="stream_start"
    )

    payload = json.dumps(
        {
            "v": 1,
            "type": "ack",
            "command_id": str(cid),
            "lease_id": str(lid),
            "sn": sn,
            "result": "nack",
            "code": "unsupported",
            "message": "Unsupported command type",
            "terminal_time_ms": 1234567,
        }
    ).encode("utf-8")

    res = await handle_device_ctl_message(
        routing_key=f"dev.{sn}.ctl",
        payload=payload,
        p_registry=p_reg,
        cmd_registry=cmd_reg,
    )
    assert res is True
    assert fut.done()
    p_res = fut.result()
    assert p_res.result == "nack"
    assert p_res.code == "unsupported"
    assert p_res.message == "Unsupported command type"


@pytest.mark.asyncio
async def test_presence_fallback_inventory_from_screen():
    p_reg = PresenceRegistry()
    sn = "SNTEST_SCREEN"

    payload = json.dumps(
        {
            "v": 1,
            "type": "presence",
            "status": "online",
            "desktop_available": True,
            "timestamp": "2026-09-10T12:00:00Z",
            "screen": {
                "virtual_x": 0,
                "virtual_y": 0,
                "virtual_width": 4920,
                "virtual_height": 1080,
            },
        }
    ).encode("utf-8")

    res = await handle_device_ctl_message(
        routing_key=f"dev.{sn}.ctl",
        payload=payload,
        p_registry=p_reg,
        cmd_registry=PendingCommandRegistry(),
    )
    assert res is True

    inv = await p_reg.get_inventory(sn)
    assert len(inv.displays) == 1
    assert inv.displays[0].desktop_id == "0"
    assert inv.displays[0].width == 4920
    assert inv.displays[0].height == 1080
    assert inv.displays[0].primary is True

    status_view = await p_reg.get(sn)
    assert status_view.inventory is not None
    assert len(status_view.inventory.displays) == 1
    assert status_view.inventory.displays[0].desktop_id == "0"
