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
