from __future__ import annotations

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from starlette.datastructures import Headers, QueryParams

from core.config import settings
from core.remote_input.leases import LeaseRegistry, lease_registry
from core.remote_input.mqtt_bridge import handle_device_ctl_message
from core.remote_input.pending import (
    PendingCommandRegistry,
    PendingResult,
    pending_registry,
)
from core.remote_input.presence import PresenceRegistry, presence_registry
from core.remote_input.rate_limit import RateLimiter
from core.remote_input.schemas import (
    ClickRequest,
    CtlPresence,
    MouseClickCommand,
    ShortcutActionCommand,
    ShortcutRequest,
    WsInboundAdapter,
    WsMouseClick,
    WsShortcutAction,
)
from core.remote_input.service import RemoteInputService
from main import main_app as app


@pytest.fixture
def test_env():
    leases = LeaseRegistry()
    presence = PresenceRegistry()
    pending = PendingCommandRegistry()
    limiter = RateLimiter()
    srv = RemoteInputService(
        leases=leases, presence=presence, pending=pending, limiter=limiter
    )
    return srv, leases, presence, pending, limiter


# ── 1. Проверка валидации координат и кнопок mouse_click ──────────────────────


def test_mouse_click_schema_right_button():
    """mouse_click обязан поддерживать button='right', default='left'."""
    cmd = MouseClickCommand(
        command_id=uuid4(),
        lease_id=uuid4(),
        sn="SN123",
        x=32768,
        y=32768,
        button="right",
        issued_at_ms=1000,
        expires_at_ms=6000,
    )
    assert cmd.button == "right"

    req = ClickRequest(x=100, y=200, button="right")
    assert req.button == "right"

    ws_msg = WsInboundAdapter.validate_json(
        b'{"type": "mouse_click", "x": 32768, "y": 32768, "button": "right"}'
    )
    assert isinstance(ws_msg, WsMouseClick)
    assert ws_msg.button == "right"


def test_mouse_click_schema_rejects_middle_and_unknown():
    """mouse_click обязан отклонять middle и неизвестные значения button."""
    with pytest.raises(ValidationError):
        ClickRequest(x=100, y=200, button="middle")  # type: ignore

    with pytest.raises(ValidationError):
        WsInboundAdapter.validate_json(
            b'{"type": "mouse_click", "x": 100, "y": 200, "button": "middle"}'
        )

    with pytest.raises(ValidationError):
        ClickRequest(x=100, y=200, button="wheel_up")  # type: ignore


def test_mouse_click_schema_rejects_non_integer_and_out_of_range_coords():
    """x, y должны быть целыми 0..65535, не округляться и не обрезаться молча."""
    with pytest.raises(ValidationError):
        ClickRequest(x=12.5, y=200)  # type: ignore

    with pytest.raises(ValidationError):
        ClickRequest(x=100, y=65536)

    with pytest.raises(ValidationError):
        ClickRequest(x=-1, y=200)

    with pytest.raises(ValidationError):
        WsInboundAdapter.validate_json(
            b'{"type": "mouse_click", "x": 10.5, "y": 200, "button": "left"}'
        )


# ── 2. Проверка валидации shortcut_action ────────────────────────────────────


def test_shortcut_action_schema_valid_actions():
    """shortcut_action обязан поддерживать только f12, alt_f4, win_d."""
    for act in ["f12", "alt_f4", "win_d"]:
        req = ShortcutRequest(action=act, client_ref="ref-1")
        assert req.action == act
        assert req.client_ref == "ref-1"

        ws_msg = WsInboundAdapter.validate_json(
            f'{{"type": "shortcut_action", "action": "{act}", "client_ref": "ref-1"}}'.encode()
        )
        assert isinstance(ws_msg, WsShortcutAction)
        assert ws_msg.action == act


def test_shortcut_action_schema_rejects_unknown_action():
    """shortcut_action обязан отклонять неизвестные действия (нет fallback в клавиши)."""
    with pytest.raises(ValidationError):
        ShortcutRequest(action="ctrl_alt_del")  # type: ignore

    with pytest.raises(ValidationError):
        WsInboundAdapter.validate_json(
            b'{"type": "shortcut_action", "action": "ctrl_alt_del"}'
        )


# ── 3. Политики безопасности (Policy Guards) ──────────────────────────────────


@pytest.mark.asyncio
async def test_shortcut_action_blocked_by_default_policy(test_env, monkeypatch):
    """По умолчанию alt_f4 и win_d запрещены; f12 запрещен без профиля приложения."""
    srv, leases, presence, _, _ = test_env

    # Настраиваем онлайн присутствие с поддержкой версии 1.7.2
    await presence.update(
        "SN_POL",
        CtlPresence(
            v=1,
            type="presence",
            agent="l4desk",
            version="1.7.2",
            status="online",
            desktop_available=True,
            timestamp="2026-09-14T12:00:00Z",
        ),
    )

    lease = await leases.acquire(
        org_id=1,
        device_id=10,
        sn="SN_POL",
        owner_user_id="user1",
        owner_role="admin",
        ttl_sec=60,
    )
    lease.stream_mode = "desktop"
    lease.selected_desktop_id = "0"
    lease.stream_instance_id = uuid4()

    # Все флаги политики False по умолчанию
    monkeypatch.setattr(settings.remote_input, "allow_f12", False)
    monkeypatch.setattr(settings.remote_input, "allow_alt_f4", False)
    monkeypatch.setattr(settings.remote_input, "allow_win_d", False)
    monkeypatch.setattr(settings.remote_input, "maintenance_profile", False)
    monkeypatch.setattr(settings.remote_input, "app_profile", False)

    for action in ["f12", "alt_f4", "win_d"]:
        with pytest.raises(HTTPException) as exc_info:
            await srv.shortcut_action(
                lease_id=lease.lease_id,
                org_id=1,
                action=action,  # type: ignore
                caller_user_id="user1",
            )
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "action_blocked_policy"


@pytest.mark.asyncio
async def test_shortcut_action_allowed_with_policy_profile(test_env, monkeypatch):
    """При подтвержденном профиле обслуживания alt_f4 и win_d разрешены, f12 при app_profile."""
    srv, leases, presence, pending, _ = test_env

    await presence.update(
        "SN_POL_OK",
        CtlPresence(
            v=1,
            type="presence",
            agent="l4desk",
            version="1.7.2",
            status="online",
            desktop_available=True,
            timestamp="2026-09-14T12:00:00Z",
        ),
    )

    lease = await leases.acquire(
        org_id=1,
        device_id=10,
        sn="SN_POL_OK",
        owner_user_id="user1",
        owner_role="admin",
        ttl_sec=60,
    )
    lease.stream_mode = "desktop"
    lease.selected_desktop_id = "0"
    lease.stream_instance_id = uuid4()

    monkeypatch.setattr(settings.remote_input, "allow_f12", True)
    monkeypatch.setattr(settings.remote_input, "maintenance_profile", True)

    with patch(
        "core.remote_input.service.send_ctl_command", new_callable=AsyncMock
    ) as mock_send:
        # Simulate terminal sending ACK
        async def delayed_ack():
            await asyncio.sleep(0.01)
            async with pending._lock:
                cmd_id = next(iter(pending._pending.keys()))
            await pending.resolve(cmd_id, PendingResult(result="injected"))

        asyncio.create_task(delayed_ack())

        res = await srv.shortcut_action(
            lease_id=lease.lease_id,
            org_id=1,
            action="f12",
            caller_user_id="user1",
        )
        assert res.result == "injected"
        assert mock_send.call_count == 1
        cmd_arg = mock_send.call_args[0][1]
        assert isinstance(cmd_arg, ShortcutActionCommand)
        assert cmd_arg.action == "f12"


@pytest.mark.asyncio
async def test_key_event_f12_blocked_when_policy_blocks_f12(test_env, monkeypatch):
    """Нельзя обойти запрет F12 через обычный key_event с vk=123 (0x7B)."""
    srv, leases, _, _, _ = test_env

    lease = await leases.acquire(
        org_id=1,
        device_id=10,
        sn="SN_KEY_BYPASS",
        owner_user_id="user1",
        owner_role="admin",
        ttl_sec=60,
    )
    lease.stream_mode = "desktop"
    lease.selected_desktop_id = "0"

    monkeypatch.setattr(settings.remote_input, "allow_f12", False)
    monkeypatch.setattr(settings.remote_input, "app_profile", False)

    with pytest.raises(HTTPException) as exc_info:
        await srv.key_event(
            lease_id=lease.lease_id,
            org_id=1,
            kind="press",
            vk=0x7B,  # VK_F12 = 123
            caller_user_id="user1",
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "action_blocked_policy"


# ── 4. Проверка совместимости версий consumer ─────────────────────────────────


@pytest.mark.asyncio
async def test_new_actions_rejected_on_old_or_unconfirmed_consumer(test_env):
    """Новые действия (shortcut_action, right click) отклоняются при старой или неподтвержденной версии consumer."""
    srv, leases, presence, _, _ = test_env

    # 1. Consumer без версии (legacy v1.0.0 или неподтвержденная)
    await presence.update(
        "SN_OLD",
        CtlPresence(
            v=1,
            type="presence",
            agent="l4desk",
            version="1.0.0",
            status="online",
            desktop_available=True,
            timestamp="2026-09-14T12:00:00Z",
        ),
    )

    lease = await leases.acquire(
        org_id=1,
        device_id=10,
        sn="SN_OLD",
        owner_user_id="user1",
        owner_role="admin",
        ttl_sec=60,
    )
    lease.stream_mode = "desktop"
    lease.selected_desktop_id = "0"
    lease.stream_instance_id = uuid4()

    # shortcut_action отклоняется из-за несовместимости consumer
    with pytest.raises(HTTPException) as exc_info:
        await srv.shortcut_action(
            lease_id=lease.lease_id,
            org_id=1,
            action="f12",
            caller_user_id="user1",
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "consumer_version_unsupported"

    # right click также отклоняется на старом агенте
    with pytest.raises(HTTPException) as exc_info2:
        await srv.mouse_click(
            lease_id=lease.lease_id,
            org_id=1,
            x=100,
            y=200,
            button="right",
            caller_user_id="user1",
        )
    assert exc_info2.value.status_code == 409
    assert exc_info2.value.detail == "consumer_version_unsupported"


# ── 5. Защита от позднего ответа прежней эпохи / сессии ───────────────────────


@pytest.mark.asyncio
async def test_late_ack_old_lease_epoch_does_not_resolve_new_lease():
    """Поздний ответ прежней сессии / аренды не должен завершать команду новой аренды."""
    cmd_reg = PendingCommandRegistry()
    cid = uuid4()
    old_lid = uuid4()
    new_lid = uuid4()

    # Регистрируем команду в контексте new_lid
    future = await cmd_reg.register(
        command_id=cid,
        lease_id=new_lid,
        sn="SN_EPOCH",
        cmd_type="mouse_click",
        timeout_sec=5.0,
    )

    # Приходит запоздалый ответ с прежним lease_id
    late_payload = {
        "v": 1,
        "type": "ack",
        "command_id": str(cid),
        "lease_id": str(old_lid),
        "sn": "SN_EPOCH",
        "result": "injected",
    }

    handled = await handle_device_ctl_message(
        routing_key="dev.SN_EPOCH.ctl",
        payload=late_payload,
        cmd_registry=cmd_reg,
    )
    # Поздний ACK со старым lease_id не должен зарезолвить команду новой эпохи!
    assert handled is False
    assert not future.done()


# ── 6. REST API, WebSocket и Upstream Budgets ─────────────────────────────────


class DummyWS:
    def __init__(
        self,
        headers: dict[str, str],
        query_params: dict[str, str] | None = None,
    ) -> None:
        self.headers = Headers(headers)
        self.query_params = QueryParams(query_params or {})
        self.accepted = False
        self.close_code: int | None = None
        self.sent_messages: list[dict] = []
        self.receive_queue: asyncio.Queue[str] = asyncio.Queue()

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000) -> None:
        self.close_code = code

    async def send_json(self, message: dict) -> None:
        self.sent_messages.append(message)

    async def receive_text(self) -> str:
        return await self.receive_queue.get()


@pytest.mark.asyncio
async def test_rest_shortcut_endpoints_and_validation(monkeypatch):
    """Проверка REST эндпоинтов /shortcut и /shortcut-action: валидация, policy, 422 для нецелых координат."""
    monkeypatch.setattr(settings.auth, "internal_service_key", "test-svc-key")

    lease = await lease_registry.acquire(
        org_id=1,
        device_id=10,
        sn="SN_REST_SC",
        owner_user_id="user1",
        owner_role="admin",
        owner_session_id="sess_123",
        ttl_sec=60,
    )
    lease.stream_mode = "desktop"
    lease.selected_desktop_id = "0"
    lease.stream_instance_id = uuid4()

    await presence_registry.update(
        "SN_REST_SC",
        CtlPresence(
            v=1,
            type="presence",
            agent="l4desk",
            version="1.7.2",
            status="online",
            desktop_available=True,
            timestamp="2026-09-14T12:00:00Z",
        ),
    )

    headers = {
        "X-Internal-Service-Key": "test-svc-key",
        "X-Org-Id": "1",
        "X-User-Id": "user1",
        "X-Session-Id": "sess_123",
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 1. По умолчанию шорткат заблокирован политикой -> 403 action_blocked_policy
        monkeypatch.setattr(settings.remote_input, "allow_f12", False)
        monkeypatch.setattr(settings.remote_input, "app_profile", False)

        r_pol = await client.post(
            f"/api/internal/v1/remote-input/lease/{lease.lease_id}/shortcut",
            headers=headers,
            json={"action": "f12"},
        )
        assert r_pol.status_code == 403
        assert r_pol.json()["detail"] == "action_blocked_policy"

        # 2. Неизвестное действие -> 422
        r_unk = await client.post(
            f"/api/internal/v1/remote-input/lease/{lease.lease_id}/shortcut",
            headers=headers,
            json={"action": "ctrl_alt_del"},
        )
        assert r_unk.status_code == 422

        # 3. Нецелые координаты в mouse-click -> 422 (не округляются молча!)
        r_float = await client.post(
            f"/api/internal/v1/remote-input/lease/{lease.lease_id}/mouse-click",
            headers=headers,
            json={"x": 100.5, "y": 200, "button": "left"},
        )
        assert r_float.status_code == 422

        # 4. Разрешаем политику f12 и эмулируем ACK от терминала
        monkeypatch.setattr(settings.remote_input, "allow_f12", True)

        with patch(
            "core.remote_input.service.send_ctl_command", new_callable=AsyncMock
        ):

            async def delayed_ack():
                await asyncio.sleep(0.01)
                async with pending_registry._lock:
                    cmd_id = next(iter(pending_registry._pending.keys()))
                await pending_registry.resolve(cmd_id, PendingResult(result="injected"))

            asyncio.create_task(delayed_ack())

            r_ok = await client.post(
                f"/api/internal/v1/remote-input/lease/{lease.lease_id}/shortcut-action",
                headers=headers,
                json={"action": "f12", "client_ref": "ref_ok"},
            )
            assert r_ok.status_code == 200
            data = r_ok.json()
            assert data["result"] == "injected"
            assert data["client_ref"] == "ref_ok"


@pytest.mark.asyncio
async def test_ws_shortcut_action_and_key_policy_guard(monkeypatch):
    """Проверка WsShortcutAction и невозможности обхода политики через WS."""
    from api.internal_v1.remote_input import remote_input_ws

    monkeypatch.setattr(settings.auth, "internal_service_key", "test-svc-key")

    lease = await lease_registry.acquire(
        org_id=1,
        device_id=10,
        sn="SN_WS_SC",
        owner_user_id="user1",
        owner_role="admin",
        owner_session_id="sess_ws",
        ttl_sec=60,
    )
    lease.stream_mode = "desktop"
    lease.selected_desktop_id = "0"
    lease.stream_instance_id = uuid4()

    await presence_registry.update(
        "SN_WS_SC",
        CtlPresence(
            v=1,
            type="presence",
            agent="l4desk",
            version="1.7.2",
            status="online",
            desktop_available=True,
            timestamp="2026-09-14T12:00:00Z",
        ),
    )

    ws = DummyWS(
        headers={
            "X-Internal-Service-Key": "test-svc-key",
            "X-Org-Id": "1",
            "X-User-Id": "user1",
            "X-Session-Id": "sess_ws",
        }
    )

    # Запрещаем Alt+F4
    monkeypatch.setattr(settings.remote_input, "allow_alt_f4", False)
    monkeypatch.setattr(settings.remote_input, "maintenance_profile", False)

    ws_task = asyncio.create_task(remote_input_ws(cast(Any, ws), lease.lease_id))
    await asyncio.sleep(0.05)

    # 1. Посылаем WsShortcutAction с запрещенным действием alt_f4
    await ws.receive_queue.put(
        '{"type": "shortcut_action", "action": "alt_f4", "client_ref": "c_ws_1"}'
    )
    await asyncio.sleep(0.05)

    err_msg = next(
        (m for m in ws.sent_messages if m.get("code") == "action_blocked_policy"), None
    )
    assert err_msg is not None
    assert err_msg["client_ref"] == "c_ws_1"

    # 2. Попытка обхода через WsKeyEvent с vk=123 (F12) при запрещенной политике
    monkeypatch.setattr(settings.remote_input, "allow_f12", False)
    await ws.receive_queue.put(
        '{"type": "key_event", "kind": "press", "vk": 123, "client_ref": "c_ws_key"}'
    )
    await asyncio.sleep(0.05)

    key_err = next(
        (m for m in ws.sent_messages if m.get("client_ref") == "c_ws_key"), None
    )
    assert key_err is not None
    assert key_err.get("code") == "action_blocked_policy"

    # Завершаем WS
    await ws.receive_queue.put('{"type": "release"}')
    await asyncio.wait_for(ws_task, timeout=1.0)


@pytest.mark.asyncio
async def test_upstream_budgets_stream_start_and_inventory(monkeypatch, test_env):
    """Проверка реальных upstream budgets app1: stream_start 15s, inventory 5s -> 504 terminal_timeout."""
    srv, leases, presence, _, _ = test_env

    # 1. stream_start budget: 15s (настраиваемый stream_start_timeout_sec)
    assert settings.remote_input.stream_start_timeout_sec == 15
    # 2. inventory budget: 5s (настраиваемый inventory_timeout_sec)
    assert settings.remote_input.inventory_timeout_sec == 5

    # Проверяем, что при истечении ожидания возвращается 504 с причиной terminal_timeout
    lease = await leases.acquire(
        org_id=1,
        device_id=10,
        sn="SN_BUDGET",
        owner_user_id="user1",
        owner_role="admin",
        ttl_sec=60,
    )

    # stream_start timeout
    with patch("core.remote_input.service.send_ctl_command", new_callable=AsyncMock):
        with pytest.raises(HTTPException) as exc_stream:
            # временно уменьшаем таймаут для быстрого теста
            monkeypatch.setattr(settings.remote_input, "stream_start_timeout_sec", 0.05)
            await srv.stream_start(
                lease_id=lease.lease_id,
                org_id=1,
                mode="desktop",
                source_id="0",
                caller_user_id="user1",
            )
        assert exc_stream.value.status_code == 504
        assert exc_stream.value.detail == "terminal_timeout"

    # inventory timeout
    with patch("core.remote_input.service.send_ctl_command", new_callable=AsyncMock):
        with pytest.raises(HTTPException) as exc_inv:
            monkeypatch.setattr(settings.remote_input, "inventory_timeout_sec", 0.05)
            await srv.get_inventory(
                session=AsyncMock(),
                sn="SN_BUDGET",
                org_id=1,
                refresh=True,
            )
        assert exc_inv.value.status_code == 504
        assert exc_inv.value.detail == "terminal_timeout"
