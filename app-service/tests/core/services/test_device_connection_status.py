import asyncio
from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession
from typing import cast

from core.crud.device_repo import DeviceRepo
from core.models import DeviceConnection
from core.schemas.devices import DeviceConnectStatus, DeviceConnectView
from core.schemas.rmq_admin import DeviceConnectionDetails
from core.services.devices import DeviceService, extract_device_sn
from core.services.rmq_admin import RmqAdmin
from core.integrations.rmq_admin_api import (
    RmqAdminApi,
    extract_device_sn_from_conn,
    IGNORED_USERS,
)


@pytest.mark.asyncio
async def test_reconcile_device_connections_bidirectional(monkeypatch):
    """Тест двусторонней сверки:
    - Устройство онлайн в RMQ и оффлайн в БД -> становится last_checked_result=True
    - Устройство отсутствует в RMQ и онлайн в БД -> становится last_checked_result=False
    - app_connect и svc_connect сохраняются без изменений.
    """
    conn_dev1 = DeviceConnection(
        device_id=1,
        client_id="SN_DEV_1",
        last_checked_result=False,
        app_connect=True,
        svc_connect=False,
        details={},
    )
    conn_dev2 = DeviceConnection(
        device_id=2,
        client_id="SN_DEV_2",
        last_checked_result=True,
        app_connect=True,
        svc_connect=True,
        details={"conn_name": "old_socket"},
    )
    conn_dev3 = DeviceConnection(
        device_id=3,
        client_id="SN_DEV_3",
        last_checked_result=True,
        app_connect=None,
        svc_connect=None,
        details={},
    )

    db_conns = [conn_dev1, conn_dev2, conn_dev3]

    async def fake_get_all_connections(session):
        return db_conns

    async def fake_rmq_get_all(time_budget_sec=10.0, page_size=100):
        return [
            {
                "user": "SN_DEV_1",
                "name": "127.0.0.1:50001 -> 127.0.0.1:5672",
                "peer_host": "192.168.1.10",
                "peer_port": 50001,
                "protocol": "MQTT 3.1.1",
                "ssl": True,
                "ssl_cipher": "TLS_AES_256_GCM_SHA384",
                "ssl_protocol": "tlsv1.3",
                "peer_cert_subject": "CN=SN_DEV_1",
                "connected_at": 1700000000000,
                "recv_oct": 512,
                "send_oct": 1024,
            },
            {
                "user": "SN_DEV_3",
                "name": "127.0.0.1:50003 -> 127.0.0.1:5672",
                "peer_host": "192.168.1.30",
                "peer_port": 50003,
                "connected_at": 1700000002000,
            },
        ]

    mock_session = AsyncMock(spec=AsyncSession)
    monkeypatch.setattr(DeviceRepo, "get_all_connections", fake_get_all_connections)
    monkeypatch.setattr(RmqAdminApi, "get_all_connections", fake_rmq_get_all)

    stats = await DeviceService.reconcile_device_connections(mock_session)

    assert stats["total_db"] == 3
    assert stats["online_rmq"] == 2
    assert stats["reconciled_online"] == 1
    assert stats["reconciled_offline"] == 1
    assert stats["updated_telemetry"] == 2

    # DEV 1 (был False, в RMQ есть) -> стал True
    assert conn_dev1.last_checked_result is True
    assert conn_dev1.app_connect is True
    assert conn_dev1.svc_connect is False
    assert conn_dev1.details["peer_host"] == "192.168.1.10"
    assert conn_dev1.details["ssl_cipher"] == "TLS_AES_256_GCM_SHA384"
    assert conn_dev1.details["bytes_received"] == 512

    # DEV 2 (был True, в RMQ отсутствует) -> стал False, но app_connect/svc_connect НЕ сбросились
    assert conn_dev2.last_checked_result is False
    assert conn_dev2.app_connect is True
    assert conn_dev2.svc_connect is True
    assert conn_dev2.details.get("conn_name") is None

    # DEV 3 (был True, в RMQ есть) -> остался True
    assert conn_dev3.last_checked_result is True


@pytest.mark.asyncio
async def test_reconcile_device_connections_time_budget(monkeypatch):
    """Тест соблюдения временного бюджета при сверке."""
    # Создаем 150 устройств
    db_conns = [
        DeviceConnection(
            device_id=i,
            client_id=f"SN_{i:04d}",
            last_checked_result=False,
            details={},
        )
        for i in range(150)
    ]

    async def fake_get_all_connections(session):
        return db_conns

    async def fake_rmq_get_all(time_budget_sec=10.0, page_size=100):
        return []

    mock_session = AsyncMock(spec=AsyncSession)
    monkeypatch.setattr(DeviceRepo, "get_all_connections", fake_get_all_connections)
    monkeypatch.setattr(RmqAdminApi, "get_all_connections", fake_rmq_get_all)

    # Задаем нулевой бюджет времени
    stats = await DeviceService.reconcile_device_connections(
        mock_session, time_budget=0.0, chunk_size=50
    )
    assert stats["total_db"] == 150


@pytest.mark.asyncio
async def test_handle_connection_created_event(monkeypatch):
    mock_session = AsyncMock(spec=AsyncSession)
    mock_row = DeviceConnection(
        device_id=10,
        client_id="SN_TEST_CREATED",
        last_checked_result=False,
        app_connect=True,
        svc_connect=True,
        details={},
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_row
    mock_session.execute.return_value = mock_result

    payload = {
        "user": "SN_TEST_CREATED",
        "name": "127.0.0.1:51111 -> 127.0.0.1:5672",
        "peer_host": "10.0.0.5",
        "peer_port": 51111,
        "ssl_cipher": "TLS_AES_256_GCM_SHA384",
        "connected_at": 1740000000000,
    }

    res = await DeviceService.handle_connection_event(
        session=mock_session,
        routing_key="connection.created",
        payload=payload,
        headers={},
    )

    assert res is True
    assert mock_row.last_checked_result is True
    assert mock_row.app_connect is True
    assert mock_row.svc_connect is True
    assert mock_row.details["conn_name"] == "127.0.0.1:51111 -> 127.0.0.1:5672"
    assert mock_row.details["peer_host"] == "10.0.0.5"
    assert mock_session.commit.await_count == 1


@pytest.mark.asyncio
async def test_handle_connection_closed_event_and_race_condition(monkeypatch):
    mock_session = AsyncMock(spec=AsyncSession)

    # 1. Нормальное закрытие
    mock_row = DeviceConnection(
        device_id=10,
        client_id="SN_TEST_CLOSED",
        last_checked_result=True,
        app_connect=True,
        svc_connect=True,
        details={"conn_name": "conn_socket_1"},
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_row
    mock_session.execute.return_value = mock_result

    res = await DeviceService.handle_connection_event(
        session=mock_session,
        routing_key="connection.closed",
        payload={"user": "SN_TEST_CLOSED", "name": "conn_socket_1"},
        headers={},
    )
    assert res is True
    assert mock_row.last_checked_result is False
    # app_connect и svc_connect должны остаться неизменными!
    assert mock_row.app_connect is True
    assert mock_row.svc_connect is True
    assert mock_row.details["conn_name"] is None

    # 2. Устаревшее событие закрытия (Race condition / Flapping: сокет уже сменился)
    mock_row2 = DeviceConnection(
        device_id=11,
        client_id="SN_TEST_FLAPPING",
        last_checked_result=True,
        app_connect=True,
        svc_connect=True,
        details={"conn_name": "conn_socket_NEW"},
    )
    mock_result2 = MagicMock()
    mock_result2.scalar_one_or_none.return_value = mock_row2
    mock_session.execute.return_value = mock_result2

    res2 = await DeviceService.handle_connection_event(
        session=mock_session,
        routing_key="connection.closed",
        payload={"user": "SN_TEST_FLAPPING", "name": "conn_socket_OLD"},
        headers={},
    )
    # Событие со старым именем сокета должно быть проигнорировано
    assert res2 is False
    assert mock_row2.last_checked_result is True


@pytest.mark.asyncio
async def test_handle_connection_event_ignores_internal_users():
    mock_session = AsyncMock(spec=AsyncSession)
    for internal_user in ["guest", "admin", "user", "root"]:
        res = await DeviceService.handle_connection_event(
            session=mock_session,
            routing_key="connection.created",
            payload={"user": internal_user, "name": "backend_sock"},
            headers={},
        )
        assert res is False
        assert mock_session.commit.await_count == 0


@pytest.mark.asyncio
async def test_extract_device_sn_helpers():
    # Из user
    assert (
        extract_device_sn({"user": "SN_A1"}, {}) == "SN_A1"
    )
    # Из client_properties.client_id
    assert (
        extract_device_sn(
            {"user": "guest", "client_properties": {"client_id": "SN_B2"}}, {}
        )
        == "SN_B2"
    )
    # Игнорируемый пользователь
    assert extract_device_sn({"user": "admin"}, {}) is None


@pytest.mark.asyncio
async def test_update_connect_flag_sql_generation():
    mock_session = AsyncMock(spec=AsyncSession)

    # Test app_connect flag update with value=True
    await DeviceRepo.update_connect_flag(mock_session, "SN123", "app_connect", True)
    assert mock_session.execute.await_count == 1
    stmt = mock_session.execute.call_args[0][0]
    compiled = str(stmt.compile())
    assert "tb_device_connections" in compiled
    assert "app_connect" in compiled

    # Test svc_connect flag update with value=False
    mock_session.reset_mock()
    await DeviceRepo.update_connect_flag(mock_session, "SN123", "svc_connect", False)
    assert mock_session.execute.await_count == 1
    stmt = mock_session.execute.call_args[0][0]
    compiled = str(stmt.compile())
    assert "tb_device_connections" in compiled
    assert "svc_connect" in compiled

    # Test invalid flag name
    with pytest.raises(ValueError, match="Invalid connection flag name"):
        await DeviceRepo.update_connect_flag(mock_session, "SN123", "unknown_flag", True)


def test_device_connection_availability_computation():
    # 1. Онлайн физически + app_connect=True -> is_app_available=True
    view1 = DeviceConnectView(
        device_id=1,
        client_id="SN001",
        last_checked_result=True,
        app_connect=True,
        svc_connect=False,
    )
    assert view1.is_app_available is True
    assert view1.is_svc_available is False

    # 2. Оффлайн физически + app_connect=True -> is_app_available=False
    view2 = DeviceConnectView(
        device_id=2,
        client_id="SN002",
        last_checked_result=False,
        app_connect=True,
        svc_connect=True,
    )
    assert view2.is_app_available is False
    assert view2.is_svc_available is False

    # 3. Онлайн физически + app_connect=False -> is_app_available=False
    view3 = DeviceConnectView(
        device_id=3,
        client_id="SN003",
        last_checked_result=True,
        app_connect=False,
        svc_connect=True,
    )
    assert view3.is_app_available is False
    assert view3.is_svc_available is True

    # 4. Legacy устройство (app_connect=None)
    view4 = DeviceConnectView(
        device_id=4,
        client_id="SN004",
        last_checked_result=True,
        app_connect=None,
        svc_connect=None,
    )
    assert view4.is_app_available is None
    assert view4.is_svc_available is None
