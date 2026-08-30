from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.crud.device_repo import DeviceRepo
from core.models.devices import Device, DeviceConnection, DeviceAuditLog, Org, DeviceOrgBind
from core.schemas.devices import DeviceConnectView, DeviceAuditEventView, DeviceListResult
from core.services.devices import (
    DeviceService,
    evaluate_connection_collision,
    clear_device_connection_history,
)
from core.integrations.rmq_admin_api import RmqAdminApi


@pytest.fixture(autouse=True)
def cleanup_history():
    clear_device_connection_history()
    yield
    clear_device_connection_history()


def test_evaluate_sn_collision_detection():
    """Проверяет мгновенную детекцию SN_COLLISION при конфликтующих сертификатах."""
    sn = "SN_TEST_COLLISION_1"
    now = 1000.0

    # 1. Первый коннект со старым сертификатом
    v_type, details = evaluate_connection_collision(
        sn=sn,
        peer_host="83.237.254.238",
        peer_port=53000,
        cert_validity="2026-06-02T12:34:07Z - 2027-06-02T12:34:07Z",
        conn_name="83.237.254.238:53000 -> 172.18.0.2:8883",
        now_ts=now,
    )
    assert v_type is None
    assert details is None

    # 2. Второй коннект с новым/другим сертификатом для того же SN
    v_type, details = evaluate_connection_collision(
        sn=sn,
        peer_host="91.242.213.17",
        peer_port=64000,
        cert_validity="2026-08-07T06:42:22Z - 2027-08-07T06:42:22Z",
        conn_name="91.242.213.17:64000 -> 172.18.0.2:8883",
        now_ts=now + 10.0,
    )
    assert v_type == "SN_COLLISION"
    assert details is not None
    assert len(details["cert_validities"]) == 2
    assert "83.237.254.238" in details["conflicting_hosts"]
    assert "91.242.213.17" in details["conflicting_hosts"]


def test_evaluate_device_clone_detection_multi_ip():
    """Проверяет детекцию DEVICE_CLONE при циклическом пинг-понге IP-адресов."""
    sn = "SN_TEST_CLONE_1"
    cert = "2026-08-07T06:42:22Z - 2027-08-07T06:42:22Z"
    now = 2000.0

    # 1. Host A
    v1, d1 = evaluate_connection_collision(
        sn=sn, peer_host="83.237.254.238", peer_port=53001, cert_validity=cert, conn_name=None, now_ts=now
    )
    assert v1 is None

    # 2. Host B (1-я смена хоста)
    v2, d2 = evaluate_connection_collision(
        sn=sn, peer_host="91.242.213.17", peer_port=64001, cert_validity=cert, conn_name=None, now_ts=now + 10.0
    )
    assert v2 is None

    # 3. Host A (2-я смена хоста -> пинг-понг!)
    v3, d3 = evaluate_connection_collision(
        sn=sn, peer_host="83.237.254.238", peer_port=53002, cert_validity=cert, conn_name=None, now_ts=now + 20.0
    )
    assert v3 == "DEVICE_CLONE"
    assert d3 is not None
    assert d3["host_switches"] >= 2
    assert set(d3["conflicting_hosts"]) == {"83.237.254.238", "91.242.213.17"}


def test_evaluate_device_clone_detection_3_distinct_ips():
    """Проверяет детекцию клонирования на > 2 разных IP адресов."""
    sn = "SN_TEST_CLONE_3_IPS"
    cert = "2026-08-07T06:42:22Z - 2027-08-07T06:42:22Z"
    now = 3000.0

    # 1. IP 1
    evaluate_connection_collision(sn=sn, peer_host="1.1.1.1", peer_port=1000, cert_validity=cert, conn_name=None, now_ts=now)
    # 2. IP 2
    evaluate_connection_collision(sn=sn, peer_host="2.2.2.2", peer_port=2000, cert_validity=cert, conn_name=None, now_ts=now + 5.0)
    # 3. IP 3
    v, d = evaluate_connection_collision(sn=sn, peer_host="3.3.3.3", peer_port=3000, cert_validity=cert, conn_name=None, now_ts=now + 10.0)

    assert v == "DEVICE_CLONE"
    assert d is not None
    assert set(d["conflicting_hosts"]) == {"1.1.1.1", "2.2.2.2", "3.3.3.3"}


def test_false_positive_cellular_ip_change_not_flagged():
    """Проверяет защиту от ложных срабатываний при нормальной смене IP сотового модема."""
    sn = "SN_TEST_CELLULAR_OK"
    cert = "2026-08-07T06:42:22Z - 2027-08-07T06:42:22Z"
    now = 4000.0

    # 1. Исходный IP сотовой сети
    v1, _ = evaluate_connection_collision(sn=sn, peer_host="100.64.1.1", peer_port=1000, cert_validity=cert, conn_name=None, now_ts=now)
    assert v1 is None

    # 2. Переключение на новую вышку (смена IP на 100.64.2.2)
    v2, _ = evaluate_connection_collision(sn=sn, peer_host="100.64.2.2", peer_port=1001, cert_validity=cert, conn_name=None, now_ts=now + 15.0)
    assert v2 is None

    # 3. Следующий реконнект через 60 сек на том же новом IP 100.64.2.2 (нет пинг-понга)
    v3, _ = evaluate_connection_collision(sn=sn, peer_host="100.64.2.2", peer_port=1002, cert_validity=cert, conn_name=None, now_ts=now + 75.0)
    assert v3 is None  # Не должно заблокировать!


def test_schema_serialization_and_availability_override():
    """Проверяет Pydantic схему DeviceConnectView при блокировке и наличии нарушений."""
    now = datetime.now(timezone.utc)
    audit_item = DeviceAuditEventView(
        id=1,
        device_id=6209,
        org_id=339,
        event_type="DEVICE_CLONE",
        actor="system/detector",
        details={"conflicting_hosts": ["83.237.254.238", "91.242.213.17"]},
        created_at=now,
    )

    view = DeviceConnectView(
        device_id=6209,
        client_id="SN6209",
        last_checked_result=True,
        app_connect=True,
        svc_connect=True,
        is_blocked=True,  # Заблокирован!
        violation_type="DEVICE_CLONE",
        violation_details={"reason": "Flapping"},
        recent_audit_events=[audit_item],
    )

    # При is_blocked=True вычисляемые доступности должны быть False!
    assert view.is_app_available is False
    assert view.is_svc_available is False
    assert view.is_blocked is True
    assert view.violation_type == "DEVICE_CLONE"
    assert len(view.recent_audit_events) == 1


@pytest.mark.asyncio
async def test_rmq_admin_block_unblock_methods(monkeypatch):
    """Проверяет методы RmqAdminApi.block_device_user и unblock_device_user."""
    mock_put = AsyncMock()
    mock_delete = AsyncMock()

    class MockResponse:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return [{"name": "mock_conn_1"}]

    mock_client = MagicMock()
    mock_client.put = AsyncMock(return_value=MockResponse())
    mock_client.delete = AsyncMock(return_value=MockResponse())
    mock_client.get = AsyncMock(return_value=MockResponse())
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: mock_client)

    # 1. Block user
    res_block = await RmqAdminApi.block_device_user("SN_BLOCK_TEST")
    assert res_block is True
    assert mock_client.put.called

    # 2. Unblock user
    res_unblock = await RmqAdminApi.unblock_device_user("SN_BLOCK_TEST")
    assert res_unblock is True


@pytest.mark.asyncio
async def test_device_repo_mark_blocked_and_unblock():
    """Проверяет методы mark_device_blocked и unblock_device в DeviceRepo."""
    session = AsyncMock(spec=AsyncSession)

    conn_row = DeviceConnection(
        device_id=100,
        client_id="SN100",
        last_checked_result=True,
        is_blocked=False,
    )

    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = conn_row
    session.execute.return_value = mock_res

    # 1. Mark blocked
    dev_id, org_id = await DeviceRepo.mark_device_blocked(
        session=session,
        sn="SN100",
        violation_type="DEVICE_CLONE",
        violation_details={"test": "ok"},
    )
    assert dev_id == 100
    assert conn_row.is_blocked is True
    assert conn_row.last_checked_result is False
    assert conn_row.violation_type == "DEVICE_CLONE"

    # 2. Unblock
    await DeviceRepo.unblock_device(session=session, device_id=100)
    assert conn_row.is_blocked is False
    assert conn_row.violation_type is None
