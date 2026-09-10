from __future__ import annotations

import json
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from core.remote_input.leases import LeaseRegistry
from core.remote_input.mqtt_bridge import handle_device_ctl_message
from core.remote_input.pending import PendingCommandRegistry
from core.remote_input.presence import PresenceRegistry
from core.remote_input.rate_limit import RateLimiter
from core.remote_input.schemas import (
    ALLOWED_VK_CODES,
    CtlAck,
    CtlInboundAdapter,
    CtlNack,
    CtlPresence,
    CtlStreamEvent,
    WsInboundAdapter,
    WsKeyEvent,
    WsMouseClick,
    WsPointerMove,
    WsStreamState,
)
from core.remote_input.service import RemoteInputService

# ── Тест 1: Валидация входящих сообщений от l4desk ──────────────────────────


def test_l4desk_inbound_presence_all_fields():
    """Проверка валидации presence со всеми полями: screen, inventory, stream."""
    stream_id = uuid4()
    raw = {
        "v": 1,
        "type": "presence",
        "agent": "l4desk",
        "status": "online",
        "desktop_available": True,
        "session_id": 1,
        "screen": {
            "virtual_x": 0,
            "virtual_y": 0,
            "virtual_width": 1920,
            "virtual_height": 1080,
        },
        "inventory": {
            "displays": [
                {
                    "desktop_id": "0",
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
                    "camera_id": "cam:0",
                    "name": "Integrated Camera",
                    "available": True,
                }
            ],
        },
        "stream": {
            "state": "running",
            "mode": "desktop",
            "source_id": "0",
            "stream_instance_id": str(stream_id),
            "profile": "default",
            "reason": None,
            "ffmpeg_pid": 12345,
            "started_at": "2026-09-11T00:00:00Z",
            "restart_count": 0,
        },
        "timestamp": "2026-09-11T00:00:00Z",
    }
    payload = json.dumps(raw).encode("utf-8")
    msg = CtlInboundAdapter.validate_json(payload)

    assert isinstance(msg, CtlPresence)
    assert msg.v == 1
    assert msg.type == "presence"
    assert msg.agent == "l4desk"
    assert msg.status == "online"
    assert msg.desktop_available is True
    assert msg.session_id == 1

    assert msg.screen is not None
    assert msg.screen.virtual_width == 1920
    assert msg.screen.virtual_height == 1080

    assert msg.inventory is not None
    assert len(msg.inventory.displays) == 1
    assert msg.inventory.displays[0].desktop_id == "0"
    assert msg.inventory.displays[0].policy == "input"
    assert len(msg.inventory.cameras) == 1
    assert msg.inventory.cameras[0].camera_id == "cam:0"

    assert msg.stream is not None
    assert msg.stream.state == "running"
    assert msg.stream.mode == "desktop"
    assert msg.stream.stream_instance_id == stream_id
    assert msg.stream.ffmpeg_pid == 12345


def test_l4desk_inbound_stream_event_with_and_without_sn():
    """Проверка валидации stream_event с полем sn (l4desk payload) и без него."""
    sid = uuid4()

    # С полем sn
    raw_with_sn = {
        "v": 1,
        "type": "stream_event",
        "sn": "SN_TERM_001",
        "stream_instance_id": str(sid),
        "state": "running",
        "reason": "pipeline_started",
        "timestamp": "2026-09-11T00:05:00Z",
    }
    msg_with_sn = CtlInboundAdapter.validate_json(
        json.dumps(raw_with_sn).encode("utf-8")
    )
    assert isinstance(msg_with_sn, CtlStreamEvent)
    assert msg_with_sn.sn == "SN_TERM_001"
    assert msg_with_sn.stream_instance_id == sid
    assert msg_with_sn.state == "running"
    assert msg_with_sn.reason == "pipeline_started"

    # Без поля sn
    raw_without_sn = {
        "v": 1,
        "type": "stream_event",
        "stream_instance_id": str(sid),
        "state": "stopped",
        "reason": "normal_exit",
        "timestamp": "2026-09-11T00:06:00Z",
    }
    msg_without_sn = CtlInboundAdapter.validate_json(
        json.dumps(raw_without_sn).encode("utf-8")
    )
    assert isinstance(msg_without_sn, CtlStreamEvent)
    assert msg_without_sn.sn is None
    assert msg_without_sn.stream_instance_id == sid
    assert msg_without_sn.state == "stopped"
    assert msg_without_sn.reason == "normal_exit"


@pytest.mark.parametrize("result", ["started", "switched", "stopped", "injected"])
def test_l4desk_inbound_ack_results(result: str):
    """Проверка валидации ack с результатами: started, switched, stopped, injected."""
    cid = uuid4()
    lid = uuid4()
    sid = uuid4() if result in ("started", "switched") else None
    state = (
        "running"
        if result in ("started", "switched")
        else "stopped" if result == "stopped" else None
    )

    raw = {
        "v": 1,
        "type": "ack",
        "command_id": str(cid),
        "lease_id": str(lid),
        "sn": "SN_ACK_TEST",
        "result": result,
        "terminal_time_ms": 1726000001000,
    }
    if sid:
        raw["stream_instance_id"] = str(sid)
    if state:
        raw["state"] = state

    msg = CtlInboundAdapter.validate_json(json.dumps(raw).encode("utf-8"))
    assert isinstance(msg, CtlAck)
    assert msg.result == result
    assert msg.command_id == cid
    assert msg.lease_id == lid
    assert msg.sn == "SN_ACK_TEST"
    assert msg.terminal_time_ms == 1726000001000


@pytest.mark.parametrize(
    "error_code",
    [
        "lease_mismatch",
        "desktop_mismatch",
        "stream_mismatch",
        "ffmpeg_missing",
        "ffmpeg_integrity",
        "source_not_allowed",
        "source_unavailable",
        "session_unavailable",
        "busy_transition",
        "input_not_allowed_in_camera_mode",
        "invalid_profile",
        "interactive_desktop_unavailable",
        "inject_failed",
    ],
)
def test_l4desk_inbound_nack_error_codes(error_code: str):
    """Проверка валидации nack и ack(result=nack) с кодами ошибок."""
    cid = uuid4()
    lid = uuid4()

    # Формат 1: type="nack"
    raw_nack = {
        "v": 1,
        "type": "nack",
        "command_id": str(cid),
        "lease_id": str(lid),
        "sn": "SN_NACK_TEST",
        "code": error_code,
        "message": f"Operation failed: {error_code}",
        "terminal_time_ms": 1726000002000,
    }
    msg_nack = CtlInboundAdapter.validate_json(json.dumps(raw_nack).encode("utf-8"))
    assert isinstance(msg_nack, CtlNack)
    assert msg_nack.code == error_code
    assert msg_nack.message == f"Operation failed: {error_code}"

    # Формат 2: type="ack", result="nack" (обратная совместимость l4desk)
    raw_ack_nack = {
        "v": 1,
        "type": "ack",
        "command_id": str(cid),
        "lease_id": str(lid),
        "sn": "SN_NACK_TEST",
        "result": "nack",
        "code": error_code,
        "message": f"Rejected: {error_code}",
        "terminal_time_ms": 1726000002000,
    }
    msg_ack_nack = CtlInboundAdapter.validate_json(
        json.dumps(raw_ack_nack).encode("utf-8")
    )
    assert isinstance(msg_ack_nack, CtlAck)
    assert msg_ack_nack.result == "nack"
    assert msg_ack_nack.code == error_code

    # Проверка отказа на неизвестный код
    raw_invalid = {
        "v": 1,
        "type": "nack",
        "command_id": str(cid),
        "lease_id": str(lid),
        "sn": "SN_NACK_TEST",
        "code": "completely_unsupported_error_code_xyz",
        "message": "Error",
    }
    with pytest.raises(ValidationError):
        CtlInboundAdapter.validate_json(json.dumps(raw_invalid).encode("utf-8"))


# ── Тест 2: Валидация входящих WebSocket сообщений ──────────────────────────


@pytest.mark.parametrize("coord", [0, 32768, 65535])
def test_ws_inbound_pointer_move_coordinates(coord: int):
    """Проверка валидации pointer_move с граничными и промежуточными координатами: 0, 65535, 32768."""
    raw = {"type": "pointer_move", "x": coord, "y": coord}
    msg = WsInboundAdapter.validate_json(json.dumps(raw).encode("utf-8"))
    assert isinstance(msg, WsPointerMove)
    assert msg.x == coord
    assert msg.y == coord

    # Отрицательные координаты недопустимы
    with pytest.raises(ValidationError):
        WsInboundAdapter.validate_json(
            json.dumps({"type": "pointer_move", "x": -1, "y": coord}).encode("utf-8")
        )

    # Превышение 65535 недопустимо
    with pytest.raises(ValidationError):
        WsInboundAdapter.validate_json(
            json.dumps({"type": "pointer_move", "x": coord, "y": 65536}).encode("utf-8")
        )


def test_ws_inbound_mouse_click():
    """Проверка валидации mouse_click (left button, client_ref)."""
    raw = {
        "type": "mouse_click",
        "x": 32768,
        "y": 16384,
        "button": "left",
        "client_ref": "client_req_001",
    }
    msg = WsInboundAdapter.validate_json(json.dumps(raw).encode("utf-8"))
    assert isinstance(msg, WsMouseClick)
    assert msg.x == 32768
    assert msg.y == 16384
    assert msg.button == "left"
    assert msg.client_ref == "client_req_001"

    # Неподдерживаемая кнопка мыши
    with pytest.raises(ValidationError):
        WsInboundAdapter.validate_json(
            json.dumps(
                {"type": "mouse_click", "x": 10, "y": 10, "button": "right"}
            ).encode("utf-8")
        )


@pytest.mark.asyncio
async def test_ws_inbound_key_event_and_vk_whitelist():
    """Проверка совместимости type='key_event' и type='key', whitelist vk и отказ вне whitelist."""
    # 1. Валидация type="key_event"
    raw_key_event = {
        "type": "key_event",
        "kind": "press",
        "vk": 0x0D,  # Enter
        "text": "Enter",
        "client_ref": "key_ref_1",
    }
    msg1 = WsInboundAdapter.validate_json(json.dumps(raw_key_event).encode("utf-8"))
    assert isinstance(msg1, WsKeyEvent)
    assert msg1.type in ("key_event", "key")
    assert msg1.kind == "press"
    assert msg1.vk == 0x0D
    assert msg1.text == "Enter"
    assert msg1.client_ref == "key_ref_1"

    # 2. Валидация type="key" (legacy BFF proxy compatibility)
    raw_key = {
        "type": "key",
        "kind": "down",
        "vk": 0x41,  # 'A'
        "text": "A",
        "client_ref": "key_ref_2",
    }
    msg2 = WsInboundAdapter.validate_json(json.dumps(raw_key).encode("utf-8"))
    assert isinstance(msg2, WsKeyEvent)
    assert msg2.type in ("key_event", "key")
    assert msg2.kind == "down"
    assert msg2.vk == 0x41
    assert msg2.text == "A"
    assert msg2.client_ref == "key_ref_2"

    # 3. Валидные коды vk из whitelist
    for vk in [
        0x08,
        0x09,
        0x0D,
        0x1B,
        0x20,
        0x2E,
        0x25,
        0x26,
        0x27,
        0x28,
        0x30,
        0x41,
        0x5A,
        0x70,
        0x7B,
    ]:
        assert vk in ALLOWED_VK_CODES

    # 4. Код vk вне диапазона 0..255 отвергается схемой
    with pytest.raises(ValidationError):
        WsInboundAdapter.validate_json(
            json.dumps({"type": "key", "kind": "press", "vk": 256}).encode("utf-8")
        )

    # 5. Код vk вне whitelist (0xFF): не в whitelist, отклоняется service
    assert 0xFF not in ALLOWED_VK_CODES

    leases = LeaseRegistry()
    presence = PresenceRegistry()
    pending = PendingCommandRegistry()
    limiter = RateLimiter()
    srv = RemoteInputService(
        leases=leases, presence=presence, pending=pending, limiter=limiter
    )

    lease = await leases.acquire(
        org_id=1,
        device_id=10,
        sn="SN_KEY_TEST",
        owner_user_id="user1",
        owner_role="admin",
        ttl_sec=60,
        scope="input",
    )
    lease.stream_mode = "desktop"
    lease.selected_desktop_id = "0"

    with pytest.raises(HTTPException) as exc_vk:
        await srv.key_event(
            lease_id=lease.lease_id,
            org_id=1,
            kind="press",
            vk=0xFF,
            caller_user_id="user1",
        )
    assert exc_vk.value.status_code == 400
    assert exc_vk.value.detail == "vk_not_allowed"


# ── Тест 3: Сквозная проверка mqtt_bridge на прием stream_event со sn ──────


@pytest.mark.asyncio
async def test_mqtt_bridge_e2e_stream_event_with_sn():
    """Сквозная проверка mqtt_bridge на прием stream_event со sn, без sn и при расхождении sn."""
    p_reg = PresenceRegistry()
    cmd_reg = PendingCommandRegistry()
    sn = "SN_BRIDGE_E2E"
    sid = uuid4()

    # Подписка на стрим-события через presence_registry (как это делает WebSocket)
    stream_q = await p_reg.subscribe_stream(sn)

    try:
        # 1. Прием stream_event с совпадающим sn
        payload_with_sn = json.dumps(
            {
                "v": 1,
                "type": "stream_event",
                "sn": sn,
                "stream_instance_id": str(sid),
                "state": "running",
                "reason": "stream_started_success",
                "timestamp": "2026-09-11T00:10:00Z",
            }
        ).encode("utf-8")

        res1 = await handle_device_ctl_message(
            routing_key=f"dev.{sn}.ctl",
            payload=payload_with_sn,
            p_registry=p_reg,
            cmd_registry=cmd_reg,
        )
        assert res1 is True

        stream_state = await p_reg.get_stream(sn)
        assert stream_state.state == "running"
        assert stream_state.stream_instance_id == sid
        assert stream_state.reason == "stream_started_success"

        # Проверка получения события подписчиком WebSocket
        ws_msg: WsStreamState = stream_q.get_nowait()
        assert isinstance(ws_msg, WsStreamState)
        assert ws_msg.type == "stream_state"
        assert ws_msg.state == "running"
        assert ws_msg.stream_instance_id == sid
        assert ws_msg.reason == "stream_started_success"

        # 2. Прием stream_event с несоответствующим sn (не должен ронять обработку, использует topic_sn)
        payload_mismatched_sn = json.dumps(
            {
                "v": 1,
                "type": "stream_event",
                "sn": "DIFFERENT_SN",
                "stream_instance_id": str(sid),
                "state": "stopping",
                "reason": "user_stop",
                "timestamp": "2026-09-11T00:10:05Z",
            }
        ).encode("utf-8")

        res2 = await handle_device_ctl_message(
            routing_key=f"dev.{sn}.ctl",
            payload=payload_mismatched_sn,
            p_registry=p_reg,
            cmd_registry=cmd_reg,
        )
        assert res2 is True

        stream_state2 = await p_reg.get_stream(sn)
        assert stream_state2.state == "stopping"
        assert stream_state2.reason == "user_stop"

        ws_msg2: WsStreamState = stream_q.get_nowait()
        assert ws_msg2.state == "stopping"

        # 3. Прием stream_event без sn
        payload_no_sn = json.dumps(
            {
                "v": 1,
                "type": "stream_event",
                "stream_instance_id": str(sid),
                "state": "stopped",
                "reason": "normal_exit",
                "timestamp": "2026-09-11T00:10:10Z",
            }
        ).encode("utf-8")

        res3 = await handle_device_ctl_message(
            routing_key=f"dev.{sn}.ctl",
            payload=payload_no_sn,
            p_registry=p_reg,
            cmd_registry=cmd_reg,
        )
        assert res3 is True

        stream_state3 = await p_reg.get_stream(sn)
        assert stream_state3.state == "stopped"
        assert stream_state3.reason == "normal_exit"

        ws_msg3: WsStreamState = stream_q.get_nowait()
        assert ws_msg3.state == "stopped"

    finally:
        await p_reg.unsubscribe_stream(sn, stream_q)
