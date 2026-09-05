from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from core.config import settings
from core.crud.device_repo import DeviceRepo
from core.models import db_helper, Device, DeviceConnection, DeviceTag
from core.schemas.devices import (
    DeviceConnectView,
    DeviceListResponse,
    DeviceListResult,
    DeviceStats,
    DeviceTagView,
)
from main import main_app as app


# =====================================================================
# 1. Схемы Pydantic: DeviceStats, DeviceConnectView, DeviceListResponse
# =====================================================================


def test_device_stats_model():
    stats = DeviceStats(total=10, online=7, offline=2, blocked=1)
    assert stats.total == 10
    assert stats.online == 7
    assert stats.offline == 2
    assert stats.blocked == 1


def test_device_connect_view_computed_fields():
    # 1. Default / None
    conn_none = DeviceConnectView(
        device_id=1,
        client_id="SN1",
        last_checked_result=True,
    )
    assert conn_none.is_app_available is None
    assert conn_none.is_svc_available is None
    assert conn_none.is_blocked is False

    # 2. Online and not blocked
    conn_online = DeviceConnectView(
        device_id=1,
        client_id="SN1",
        last_checked_result=True,
        app_connect=True,
        svc_connect=True,
        is_blocked=False,
    )
    assert conn_online.is_app_available is True
    assert conn_online.is_svc_available is True

    # 3. Last check failed
    conn_check_failed = DeviceConnectView(
        device_id=1,
        client_id="SN1",
        last_checked_result=False,
        app_connect=True,
        svc_connect=True,
        is_blocked=False,
    )
    assert conn_check_failed.is_app_available is False
    assert conn_check_failed.is_svc_available is False

    # 4. Blocked device
    conn_blocked = DeviceConnectView(
        device_id=1,
        client_id="SN1",
        last_checked_result=True,
        app_connect=True,
        svc_connect=True,
        is_blocked=True,
        violation_type="DEVICE_CLONE",
    )
    assert conn_blocked.is_app_available is False
    assert conn_blocked.is_svc_available is False
    assert conn_blocked.violation_type == "DEVICE_CLONE"


def test_device_connect_view_json_string_parsing():
    conn = DeviceConnectView(
        device_id=1,
        client_id="SN1",
        last_checked_result=True,
        details='{"peer_host": "83.237.254.238", "protocol": "mqtt"}',
        violation_details='{"reason": "Rapid IP hopping"}',
    )
    assert conn.details.peer_host == "83.237.254.238"
    assert isinstance(conn.violation_details, dict)
    assert conn.violation_details["reason"] == "Rapid IP hopping"


def test_device_list_response_full_contract():
    tag1 = DeviceTagView(id=1, tag="name", value="Центральный ТЦ")
    tag2 = DeviceTagView(id=2, tag="app", value="v2.1.4")
    tag3 = DeviceTagView(id=3, tag="sys", value="windows")

    conn = DeviceConnectView(
        device_id=6209,
        client_id="a4b0006209c67756d020626",
        connected_at=datetime(2026, 8, 30, 8, 33, 7, 448000, tzinfo=timezone.utc),
        checked_at=datetime(2026, 8, 30, 8, 33, 7, 470000, tzinfo=timezone.utc),
        last_checked_result=False,
        app_connect=None,
        svc_connect=None,
        is_blocked=True,
        violation_type="DEVICE_CLONE",
        violation_details={
            "detected_at": "2026-08-30T08:33:07.470000Z",
            "violation_type": "DEVICE_CLONE",
            "conflicting_hosts": ["83.237.254.238", "91.242.213.17"],
            "cert_validities": ["2026-08-07T06:42:22Z - 2027-08-07T06:42:22Z"],
            "flapping_count": 5,
            "host_switches": 4,
            "reason": "Rapid IP hopping across distinct hosts with identical credentials",
        },
        recent_audit_events=None,
        details={
            "peer_host": "83.237.254.238",
            "peer_port": 45120,
            "protocol": "mqtt",
            "ssl": True,
            "ssl_protocol": "TLSv1.3",
            "ssl_cipher": "TLS_AES_256_GCM_SHA384",
        },
    )

    item = DeviceListResult(
        id=147,
        device_id=6209,
        sn="a4b0006209c67756d020626",
        device_gauges=[],
        connection=conn,
        device_tags=[tag1, tag2, tag3],
    )

    response = DeviceListResponse(
        items=[item],
        total=1420,
        page=1,
        size=20,
        pages=71,
        stats=DeviceStats(total=1420, online=1280, offline=132, blocked=8),
    )

    data = response.model_dump(mode="json")
    assert data["total"] == 1420
    assert data["page"] == 1
    assert data["size"] == 20
    assert data["pages"] == 71
    assert data["stats"] == {
        "total": 1420,
        "online": 1280,
        "offline": 132,
        "blocked": 8,
    }
    assert len(data["items"]) == 1
    d0 = data["items"][0]
    assert d0["id"] == 147
    assert d0["device_id"] == 6209
    assert d0["sn"] == "a4b0006209c67756d020626"
    assert d0["connection"]["is_blocked"] is True
    assert d0["connection"]["violation_type"] == "DEVICE_CLONE"
    assert len(d0["device_tags"]) == 3
    assert d0["device_tags"][0] == {"id": 1, "tag": "name", "value": "Центральный ТЦ"}


# =====================================================================
# 2. Эндпоинты REST API: /api/v1/devices/ и /api/internal/v1/devices/
# =====================================================================


@pytest.fixture
def dummy_device_response():
    return DeviceListResponse(
        items=[],
        total=10,
        page=1,
        size=20,
        pages=1,
        stats=DeviceStats(total=10, online=8, offline=2, blocked=0),
    )


@pytest.mark.asyncio
async def test_public_devices_endpoint_params_and_response(dummy_device_response):
    fake_session = AsyncMock()
    fake_session.scalar.return_value = 1

    async def fake_session_getter():
        yield fake_session

    app.dependency_overrides[db_helper.session_getter] = fake_session_getter

    headers = {"x-api-key": "test"}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        with patch(
            "core.services.devices.DeviceService.get_list", new_callable=AsyncMock
        ) as mock_get_list:
            mock_get_list.return_value = dummy_device_response

            # 1. Defaults
            resp = await ac.get("/api/v1/devices/", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 10
            assert data["page"] == 1
            assert data["size"] == 20
            assert data["pages"] == 1
            assert data["stats"] == {"total": 10, "online": 8, "offline": 2, "blocked": 0}

            mock_get_list.assert_called_once_with(
                session=mock_get_list.call_args.kwargs["session"],
                org_id=1,
                device_id=None,
                page=1,
                size=20,
                q=None,
                status=None,
                sort_by="device_id",
                sort_order="asc",
            )

        # 2. Custom query parameters
        with patch(
            "core.services.devices.DeviceService.get_list", new_callable=AsyncMock
        ) as mock_get_list:
            mock_get_list.return_value = dummy_device_response

            url = (
                "/api/v1/devices/?page=2&size=50&q=terminal_1"
                "&status=online&device_id=500&sort_by=sn&sort_order=desc"
            )
            resp = await ac.get(url, headers=headers)
            assert resp.status_code == 200
            mock_get_list.assert_called_once_with(
                session=mock_get_list.call_args.kwargs["session"],
                org_id=1,
                device_id=500,
                page=2,
                size=50,
                q="terminal_1",
                status="online",
                sort_by="sn",
                sort_order="desc",
            )

        # 3. Validation: page < 1 -> 422
        resp_invalid_page = await ac.get("/api/v1/devices/?page=0", headers=headers)
        assert resp_invalid_page.status_code == 422

        # 4. Validation: size < 1 -> 422
        resp_invalid_size_low = await ac.get("/api/v1/devices/?size=0", headers=headers)
        assert resp_invalid_size_low.status_code == 422

        # 5. Validation: size > 100 -> 422
        resp_invalid_size_high = await ac.get("/api/v1/devices/?size=101", headers=headers)
        assert resp_invalid_size_high.status_code == 422

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_internal_devices_endpoint_params_and_response(
    monkeypatch, dummy_device_response
):
    monkeypatch.setattr(settings.auth, "internal_service_key", "secret123")

    async def fake_session_getter():
        yield object()

    app.dependency_overrides[db_helper.session_getter] = fake_session_getter

    headers = {
        "X-Internal-Service-Key": "secret123",
        "X-Org-Id": "42",
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        with patch(
            "core.services.devices.DeviceService.get_list", new_callable=AsyncMock
        ) as mock_get_list:
            mock_get_list.return_value = dummy_device_response

            url = (
                "/api/internal/v1/devices/?page=3&size=15&q=wifi"
                "&status=blocked&sort_by=connected_at&sort_order=desc"
            )
            resp = await ac.get(url, headers=headers)
            assert resp.status_code == 200
            assert resp.json()["total"] == 10
            mock_get_list.assert_called_once_with(
                session=mock_get_list.call_args.kwargs["session"],
                org_id=42,
                device_id=None,
                page=3,
                size=15,
                q="wifi",
                status="blocked",
                sort_by="connected_at",
                sort_order="desc",
            )

    app.dependency_overrides.clear()


# =====================================================================
# 3. Логика DeviceRepo.get: валидация, расчет stats, фильтры и сортировка
# =====================================================================


@pytest.mark.asyncio
async def test_device_repo_validation_errors():
    session = AsyncMock()

    # Invalid page
    with pytest.raises(HTTPException) as exc:
        await DeviceRepo.get(session, org_id=1, page=0)
    assert exc.value.status_code == 400
    assert "page" in exc.value.detail

    # Invalid size
    with pytest.raises(HTTPException) as exc:
        await DeviceRepo.get(session, org_id=1, size=150)
    assert exc.value.status_code == 400
    assert "size" in exc.value.detail

    # Invalid sort_by
    with pytest.raises(HTTPException) as exc:
        await DeviceRepo.get(session, org_id=1, sort_by="unsupported_column")
    assert exc.value.status_code == 400
    assert "sort_by" in exc.value.detail

    # Invalid sort_order
    with pytest.raises(HTTPException) as exc:
        await DeviceRepo.get(session, org_id=1, sort_order="random")
    assert exc.value.status_code == 400
    assert "sort_order" in exc.value.detail

    # Invalid status
    with pytest.raises(HTTPException) as exc:
        await DeviceRepo.get(session, org_id=1, status="broken")
    assert exc.value.status_code == 400
    assert "status" in exc.value.detail


@pytest.mark.asyncio
async def test_device_repo_get_success_and_query_generation():
    session = AsyncMock()

    # Mock stats result row
    stats_row = SimpleNamespace(total=100, online=80, offline=15, blocked=5)
    mock_stats_res = MagicMock()
    mock_stats_res.one.return_value = stats_row

    # Mock devices result
    mock_dev_1 = SimpleNamespace(
        id=1,
        device_id=101,
        sn="SN101",
        connection=SimpleNamespace(
            device_id=101,
            client_id="SN101",
            connected_at=None,
            checked_at=None,
            last_checked_result=True,
            app_connect=True,
            svc_connect=True,
            is_blocked=False,
            violation_type=None,
            violation_details=None,
            recent_audit_events=None,
            details=None,
        ),
        device_tags=[SimpleNamespace(id=1, tag="name", value="Test Dev")],
        device_gauges=[],
    )
    mock_devices_res = MagicMock()
    mock_devices_res.unique.return_value.scalars.return_value.all.return_value = [
        mock_dev_1
    ]

    session.execute.side_effect = [mock_stats_res, mock_devices_res]

    res = await DeviceRepo.get(
        session=session,
        org_id=10,
        page=1,
        size=20,
        sort_by="device_id",
        sort_order="asc",
    )

    assert isinstance(res, DeviceListResponse)
    assert res.total == 100
    assert res.page == 1
    assert res.size == 20
    assert res.pages == 5
    assert res.stats.total == 100
    assert res.stats.online == 80
    assert res.stats.offline == 15
    assert res.stats.blocked == 5
    assert len(res.items) == 1
    assert res.items[0].device_id == 101
    assert res.items[0].sn == "SN101"

    # Verify 2 queries were executed (stats + paginated devices)
    assert session.execute.call_count == 2
    stats_call_stmt = str(session.execute.call_args_list[0][0][0])
    devices_call_stmt = str(session.execute.call_args_list[1][0][0])

    assert "count(" in stats_call_stmt.lower()
    assert "tb_devices" in stats_call_stmt.lower()
    assert "tb_device_connections" in stats_call_stmt.lower()
    assert "tb_devices" in devices_call_stmt.lower()


@pytest.mark.asyncio
async def test_device_repo_get_with_filters_runs_filtered_count():
    session = AsyncMock()

    stats_row = SimpleNamespace(total=100, online=80, offline=15, blocked=5)
    mock_stats_res = MagicMock()
    mock_stats_res.one.return_value = stats_row

    mock_devices_res = MagicMock()
    mock_devices_res.unique.return_value.scalars.return_value.all.return_value = []

    session.execute.side_effect = [mock_stats_res, mock_devices_res]
    session.scalar.return_value = 8  # 8 filtered items

    res = await DeviceRepo.get(
        session=session,
        org_id=10,
        page=1,
        size=5,
        status="blocked",
        q="SN_TEST",
        sort_by="status",
        sort_order="desc",
    )

    assert res.total == 8
    assert res.page == 1
    assert res.size == 5
    assert res.pages == 2  # (8 + 5 - 1) // 5 = 2
    assert res.stats.total == 100
    assert res.stats.blocked == 5

    # Filtered total count query was executed
    assert session.scalar.call_count == 1
    count_call_stmt = str(session.scalar.call_args[0][0])
    assert "count(" in count_call_stmt.lower()


@pytest.mark.asyncio
async def test_device_repo_get_single_device_enriches_audit_logs():
    session = AsyncMock()

    stats_row = SimpleNamespace(total=10, online=9, offline=1, blocked=0)
    mock_stats_res = MagicMock()
    mock_stats_res.one.return_value = stats_row

    mock_conn = SimpleNamespace(
        device_id=999,
        client_id="SN999",
        connected_at=None,
        checked_at=None,
        last_checked_result=True,
        app_connect=True,
        svc_connect=True,
        is_blocked=False,
        violation_type=None,
        violation_details=None,
        recent_audit_events=None,
        details=None,
    )
    mock_dev = SimpleNamespace(
        id=5,
        device_id=999,
        sn="SN999",
        connection=mock_conn,
        device_tags=[],
        device_gauges=[],
    )
    mock_devices_res = MagicMock()
    mock_devices_res.unique.return_value.scalars.return_value.all.return_value = [
        mock_dev
    ]

    session.execute.side_effect = [mock_stats_res, mock_devices_res]
    session.scalar.return_value = 1

    audit_entry = SimpleNamespace(
        id=1,
        device_id=999,
        org_id=10,
        event_type="DEVICE_CLONE",
        actor="system",
        details={"info": "test"},
        created_at=datetime.now(timezone.utc),
    )

    with patch(
        "core.crud.device_repo.DeviceRepo.get_recent_audit_logs",
        new_callable=AsyncMock,
    ) as mock_audit_logs:
        mock_audit_logs.return_value = [audit_entry]

        res = await DeviceRepo.get(
            session=session,
            org_id=10,
            device_id=999,
        )

        assert res.total == 1
        assert len(res.items) == 1
        assert mock_audit_logs.call_count == 1
        assert mock_audit_logs.call_args[0][1] == 999
        assert len(res.items[0].connection.recent_audit_events) == 1
