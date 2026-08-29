import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

import core.topologys.fs_queues as fs_queues_module
from core.topologys.declare import BINDINGS, q_app, q_svc
from core import settings


def _make_rabbit_msg(body: bytes) -> MagicMock:
    msg = MagicMock()
    msg.body = body
    return msg


@pytest.mark.asyncio
async def test_topology_includes_lwt_queues():
    binding_destinations = [b[0].name for b in BINDINGS]
    binding_keys = [b[1] for b in BINDINGS]

    assert q_app.name == "app"
    assert q_svc.name == "svc"
    assert "app" in binding_destinations
    assert "svc" in binding_destinations
    assert "iot.device.connection.events" in binding_destinations
    assert str(settings.rmq.routing_key_dev_app) in binding_keys
    assert str(settings.rmq.routing_key_dev_svc) in binding_keys
    assert "connection.created" in binding_keys
    assert "connection.closed" in binding_keys


@pytest.mark.asyncio
async def test_device_connection_events_subscriber_calls_service(monkeypatch):
    mock_session = AsyncMock(spec=AsyncSession)
    handled_events = []

    async def fake_handle_connection_event(session, routing_key, payload, headers):
        handled_events.append((routing_key, payload, headers))
        return True

    monkeypatch.setattr(
        fs_queues_module.DeviceService,
        "handle_connection_event",
        fake_handle_connection_event,
    )

    msg = _make_rabbit_msg(b'{"user": "SN_TEST_EVENT", "name": "sock1"}')
    msg.routing_key = "connection.created"
    msg.headers = {"x-test": "1"}

    await fs_queues_module.device_connection_events_handler(msg, mock_session)

    assert len(handled_events) == 1
    assert handled_events[0][0] == "connection.created"
    assert handled_events[0][1]["user"] == "SN_TEST_EVENT"


@pytest.mark.asyncio
async def test_app_connect_handler_online(monkeypatch):
    mock_session = AsyncMock(spec=AsyncSession)
    updated_args = []

    async def fake_update_connect_flag(session, sn, flag_name, value):
        updated_args.append((sn, flag_name, value))

    monkeypatch.setattr(
        fs_queues_module.DeviceRepo, "update_connect_flag", fake_update_connect_flag
    )

    msg = _make_rabbit_msg(b"app_online")
    await fs_queues_module.app_connect_handler(msg, mock_session, "SN_TEST_001")

    assert updated_args == [("SN_TEST_001", "app_connect", True)]
    assert mock_session.commit.await_count == 1


@pytest.mark.asyncio
async def test_app_connect_handler_offline(monkeypatch):
    mock_session = AsyncMock(spec=AsyncSession)
    updated_args = []

    async def fake_update_connect_flag(session, sn, flag_name, value):
        updated_args.append((sn, flag_name, value))

    monkeypatch.setattr(
        fs_queues_module.DeviceRepo, "update_connect_flag", fake_update_connect_flag
    )

    msg = _make_rabbit_msg(b'"app_offline"')
    await fs_queues_module.app_connect_handler(msg, mock_session, "SN_TEST_002")

    assert updated_args == [("SN_TEST_002", "app_connect", False)]
    assert mock_session.commit.await_count == 1


@pytest.mark.asyncio
async def test_app_connect_handler_invalid_payload_ignored(monkeypatch):
    mock_session = AsyncMock(spec=AsyncSession)
    updated_args = []

    async def fake_update_connect_flag(session, sn, flag_name, value):
        updated_args.append((sn, flag_name, value))

    monkeypatch.setattr(
        fs_queues_module.DeviceRepo, "update_connect_flag", fake_update_connect_flag
    )

    msg = _make_rabbit_msg(b"random_invalid_string")
    await fs_queues_module.app_connect_handler(msg, mock_session, "SN_TEST_003")

    assert len(updated_args) == 0
    assert mock_session.commit.await_count == 0


@pytest.mark.asyncio
async def test_svc_connect_handler_online(monkeypatch):
    mock_session = AsyncMock(spec=AsyncSession)
    updated_args = []

    async def fake_update_connect_flag(session, sn, flag_name, value):
        updated_args.append((sn, flag_name, value))

    monkeypatch.setattr(
        fs_queues_module.DeviceRepo, "update_connect_flag", fake_update_connect_flag
    )

    msg = _make_rabbit_msg(b"svc_online\n")
    await fs_queues_module.svc_connect_handler(msg, mock_session, "SN_TEST_004")

    assert updated_args == [("SN_TEST_004", "svc_connect", True)]
    assert mock_session.commit.await_count == 1


@pytest.mark.asyncio
async def test_svc_connect_handler_offline(monkeypatch):
    mock_session = AsyncMock(spec=AsyncSession)
    updated_args = []

    async def fake_update_connect_flag(session, sn, flag_name, value):
        updated_args.append((sn, flag_name, value))

    monkeypatch.setattr(
        fs_queues_module.DeviceRepo, "update_connect_flag", fake_update_connect_flag
    )

    msg = _make_rabbit_msg(b'"svc_offline"')
    await fs_queues_module.svc_connect_handler(msg, mock_session, "SN_TEST_005")

    assert updated_args == [("SN_TEST_005", "svc_connect", False)]
    assert mock_session.commit.await_count == 1


@pytest.mark.asyncio
async def test_svc_connect_handler_invalid_payload_ignored(monkeypatch):
    mock_session = AsyncMock(spec=AsyncSession)
    updated_args = []

    async def fake_update_connect_flag(session, sn, flag_name, value):
        updated_args.append((sn, flag_name, value))

    monkeypatch.setattr(
        fs_queues_module.DeviceRepo, "update_connect_flag", fake_update_connect_flag
    )

    msg = _make_rabbit_msg(b"invalid_svc")
    await fs_queues_module.svc_connect_handler(msg, mock_session, "SN_TEST_006")

    assert len(updated_args) == 0
    assert mock_session.commit.await_count == 0


@pytest.mark.asyncio
async def test_out_handler_does_not_call_billing(monkeypatch):
    with (
        patch(
            "core.topologys.fs_queues._publish_billing_for_sn",
            new_callable=AsyncMock,
        ) as mock_billing,
        patch(
            "core.topologys.fs_queues.handle_device_output_message",
            new_callable=AsyncMock,
        ) as mock_handle,
    ):
        msg = _make_rabbit_msg(b"log output")
        await fs_queues_module.diagnostics_output(msg, "SN_OUT_TEST")
        mock_handle.assert_awaited_once()
        mock_billing.assert_not_called()


@pytest.mark.asyncio
async def test_app_and_svc_connect_handlers_json_payload(monkeypatch):
    mock_session = AsyncMock(spec=AsyncSession)
    updated_args = []

    async def fake_update_connect_flag(session, sn, flag_name, value):
        updated_args.append((sn, flag_name, value))

    monkeypatch.setattr(
        fs_queues_module.DeviceRepo, "update_connect_flag", fake_update_connect_flag
    )

    # JSON with status field
    msg1 = _make_rabbit_msg(b'{"status": "app_online"}')
    await fs_queues_module.app_connect_handler(msg1, mock_session, "SN_JSON_1")

    # JSON with boolean app_connect
    msg2 = _make_rabbit_msg(b'{"app_connect": false}')
    await fs_queues_module.app_connect_handler(msg2, mock_session, "SN_JSON_2")

    # JSON with state field for svc
    msg3 = _make_rabbit_msg(b'{"state": "svc_online"}')
    await fs_queues_module.svc_connect_handler(msg3, mock_session, "SN_JSON_3")

    # JSON with boolean svc_connect
    msg4 = _make_rabbit_msg(b'{"svc_connect": false}')
    await fs_queues_module.svc_connect_handler(msg4, mock_session, "SN_JSON_4")

    assert updated_args == [
        ("SN_JSON_1", "app_connect", True),
        ("SN_JSON_2", "app_connect", False),
        ("SN_JSON_3", "svc_connect", True),
        ("SN_JSON_4", "svc_connect", False),
    ]


@pytest.mark.asyncio
async def test_sn_getter_dep_formats():
    from core.topologys.fs_depends import sn_getter_dep

    # 1. Standard dot-separated
    msg1 = MagicMock()
    msg1.raw_message.routing_key = "dev.a4b0000773c82116d210826.app"
    assert await sn_getter_dep(msg1) == "a4b0000773c82116d210826"

    # 2. Slash-separated (MQTT standard)
    msg2 = MagicMock()
    msg2.raw_message.routing_key = "dev/a4b0000773c82116d210826/svc"
    assert await sn_getter_dep(msg2) == "a4b0000773c82116d210826"

    # 3. Custom length SN
    msg3 = MagicMock()
    msg3.raw_message.routing_key = "dev.custom_device_serial_123.app"
    assert await sn_getter_dep(msg3) == "custom_device_serial_123"
