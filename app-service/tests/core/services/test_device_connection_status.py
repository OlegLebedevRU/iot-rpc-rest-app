import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from typing import cast

from core.crud.device_repo import DeviceRepo
from core.schemas.devices import DeviceConnectStatus, DeviceConnectView
from core.schemas.rmq_admin import DeviceConnectionDetails
from core.services.devices import DeviceService
from core.services.rmq_admin import RmqAdmin


@pytest.mark.asyncio
async def test_update_device_connections_polls_only_legacy_devices(monkeypatch):
    polled_sn_list = []
    reset_sn_list = []
    updated_statuses = []

    async def fake_list(session):
        return ["SN_LWT_1", "SN_LEGACY_1", "SN_LEGACY_2"]

    async def fake_get_known(session):
        return {"SN_LWT_1"}

    async def fake_get_online_devices(sn_arr):
        polled_sn_list.extend(sn_arr)
        return [
            DeviceConnectionDetails.model_validate(
                {
                    "user": "SN_LEGACY_1",
                    "connected_at": 1700000000000,
                    "peer_host": "127.0.0.1",
                    "peer_port": 50000,
                    "protocol": "MQTT",
                    "peer_cert_subject": "CN=SN_LEGACY_1",
                    "peer_cert_validity": "valid",
                    "client_properties": {"client_id": "SN_LEGACY_1_12345678901"},
                }
            )
        ]

    async def fake_reset_flag(session, sn_arr):
        reset_sn_list.extend(sn_arr)

    async def fake_update_connections(session, statuses):
        updated_statuses.extend(statuses)

    mock_session = AsyncMock(spec=AsyncSession)

    monkeypatch.setattr(DeviceRepo, "list", fake_list)
    monkeypatch.setattr(DeviceRepo, "get_devices_with_known_connect_state", fake_get_known)
    monkeypatch.setattr(RmqAdmin, "get_online_devices", fake_get_online_devices)
    monkeypatch.setattr(DeviceRepo, "reset_connection_flag", fake_reset_flag)
    monkeypatch.setattr(DeviceRepo, "update_connections", fake_update_connections)

    await DeviceService.update_device_connections(mock_session)

    assert polled_sn_list == ["SN_LEGACY_1", "SN_LEGACY_2"]
    assert reset_sn_list == ["SN_LEGACY_1", "SN_LEGACY_2"]
    assert len(updated_statuses) == 1
    assert updated_statuses[0].client_id == "SN_LEGACY_1"
    assert updated_statuses[0].last_checked_result is True
    assert mock_session.commit.await_count == 1


@pytest.mark.asyncio
async def test_update_device_connections_skips_when_all_devices_have_lwt(monkeypatch):
    async def fake_list(session):
        return ["SN_LWT_1", "SN_LWT_2"]

    async def fake_get_known(session):
        return {"SN_LWT_1", "SN_LWT_2"}

    async def fake_get_online_devices(sn_arr):  # pragma: no cover
        raise AssertionError("RabbitMQ API must not be called when all devices have LWT")

    mock_session = AsyncMock(spec=AsyncSession)

    monkeypatch.setattr(DeviceRepo, "list", fake_list)
    monkeypatch.setattr(DeviceRepo, "get_devices_with_known_connect_state", fake_get_known)
    monkeypatch.setattr(RmqAdmin, "get_online_devices", fake_get_online_devices)

    await DeviceService.update_device_connections(mock_session)
    assert mock_session.commit.await_count == 0


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


@pytest.mark.asyncio
async def test_get_devices_with_known_connect_state_query():
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalars().all.return_value = ["SN_1", "SN_2", None]
    mock_session.execute.return_value = mock_result

    known = await DeviceRepo.get_devices_with_known_connect_state(mock_session)
    assert known == {"SN_1", "SN_2"}


def test_device_connection_schemas():
    view = DeviceConnectView(
        device_id=1,
        client_id="SN001",
        last_checked_result=True,
        app_connect=True,
        svc_connect=False,
    )
    assert view.app_connect is True
    assert view.svc_connect is False
    assert view.last_checked_result is True

    # Test default None values
    legacy_view = DeviceConnectView(
        device_id=2,
        client_id="SN002",
        last_checked_result=False,
    )
    assert legacy_view.app_connect is None
    assert legacy_view.svc_connect is None
