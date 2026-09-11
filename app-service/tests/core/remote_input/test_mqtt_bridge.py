from __future__ import annotations

import json
from uuid import uuid4

import pytest

from core.remote_input.leases import LeaseRegistry
from core.remote_input.mqtt_bridge import (
    _SN_STATUS,
    extract_sn_from_ctl_routing_key,
    handle_device_ctl_message,
)
from core.remote_input.pending import PendingCommandRegistry, PendingResult
from core.remote_input.presence import PresenceRegistry
from core.remote_input.schemas import WsStreamState


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


@pytest.mark.asyncio
async def test_presence_updates_sn_status_and_protects_against_lwt_race():
    p_reg = PresenceRegistry()
    sn = "SN_RACE_TEST"

    # 1. New process publishes online presence at 12:00:05
    online_payload = json.dumps(
        {
            "v": 1,
            "type": "presence",
            "status": "online",
            "desktop_available": True,
            "timestamp": "2026-09-11T12:00:05Z",
        }
    ).encode("utf-8")

    res1 = await handle_device_ctl_message(
        routing_key=f"dev.{sn}.ctl",
        payload=online_payload,
        p_registry=p_reg,
        cmd_registry=PendingCommandRegistry(),
    )
    assert res1 is True
    assert sn in _SN_STATUS
    assert _SN_STATUS[sn].agent.online is True

    # 2. Broker delivers delayed LWT offline packet from old crashed connection at 12:00:01
    lwt_offline_payload = json.dumps(
        {
            "v": 1,
            "type": "presence",
            "status": "offline",
            "desktop_available": False,
            "timestamp": "2026-09-11T12:00:01Z",
        }
    ).encode("utf-8")

    res2 = await handle_device_ctl_message(
        routing_key=f"dev.{sn}.ctl",
        payload=lwt_offline_payload,
        p_registry=p_reg,
        cmd_registry=PendingCommandRegistry(),
    )
    assert res2 is True
    # Stale offline must NOT turn agent offline!
    assert _SN_STATUS[sn].agent.online is True
    view = await p_reg.get(sn)
    assert view.online is True

    # 3. Genuine offline packet arrives with newer timestamp (12:00:10)
    genuine_offline_payload = json.dumps(
        {
            "v": 1,
            "type": "presence",
            "status": "offline",
            "desktop_available": False,
            "timestamp": "2026-09-11T12:00:10Z",
        }
    ).encode("utf-8")

    res3 = await handle_device_ctl_message(
        routing_key=f"dev.{sn}.ctl",
        payload=genuine_offline_payload,
        p_registry=p_reg,
        cmd_registry=PendingCommandRegistry(),
    )
    assert res3 is True
    assert _SN_STATUS[sn].agent.online is False
    view3 = await p_reg.get(sn)
    assert view3.online is False


@pytest.mark.asyncio
async def test_stream_event_stopped_resets_lease_stream_state():
    p_reg = PresenceRegistry()
    l_reg = LeaseRegistry()
    sn = "SN_STREAM_RESET"

    lease = await l_reg.acquire(
        org_id=1,
        device_id=1,
        sn=sn,
        owner_user_id="u1",
        owner_role="admin",
        ttl_sec=60,
        scope="input",
    )
    sid = uuid4()
    lease.stream_instance_id = sid
    lease.stream_state = "running"
    lease.stream_mode = "desktop"
    lease.selected_desktop_id = "0"

    stream_q = await p_reg.subscribe_stream(sn)

    try:
        stopped_payload = json.dumps(
            {
                "v": 1,
                "type": "stream_event",
                "sn": sn,
                "stream_instance_id": str(sid),
                "state": "stopped",
                "reason": "lease_expired",
                "timestamp": "2026-09-11T12:01:00Z",
            }
        ).encode("utf-8")

        handled = await handle_device_ctl_message(
            routing_key=f"dev.{sn}.ctl",
            payload=stopped_payload,
            p_registry=p_reg,
            cmd_registry=PendingCommandRegistry(),
            l_registry=l_reg,
        )
        assert handled is True

        # Active lease stream state must be reset
        assert lease.stream_state == "stopped"
        assert lease.stream_instance_id is None
        assert lease.stream_mode is None
        assert lease.selected_desktop_id is None

        # WebSocket listener must have received stream_state stopped
        ws_msg: WsStreamState = stream_q.get_nowait()
        assert isinstance(ws_msg, WsStreamState)
        assert ws_msg.type == "stream_state"
        assert ws_msg.state == "stopped"
        assert ws_msg.reason == "lease_expired"

    finally:
        await p_reg.unsubscribe_stream(sn, stream_q)
