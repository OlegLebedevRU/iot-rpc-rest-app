from __future__ import annotations

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from starlette.datastructures import Headers, QueryParams
from unittest.mock import AsyncMock, patch

from api.internal_v1.internal_depends import (
    get_internal_billing_org_id,
    get_internal_org_id,
    is_request_superuser,
)
from core.config import settings
from core.models import db_helper
from main import main_app as app


class DummyRequest:
    def __init__(
        self,
        headers: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
    ):
        self.headers = Headers(headers or {})
        self.query_params = QueryParams(query_params or {})
        self.state = type("State", (), {})()


def test_is_request_superuser():
    assert is_request_superuser(DummyRequest(headers={"X-Role": "superuser"})) is True
    assert is_request_superuser(DummyRequest(headers={"x-role": "admin"})) is True
    assert is_request_superuser(DummyRequest(headers={"jwt-role": "1"})) is True
    assert is_request_superuser(DummyRequest(headers={"X-Role-Id": "1"})) is True
    assert is_request_superuser(DummyRequest(headers={"x-role-id": "superuser"})) is True
    assert is_request_superuser(DummyRequest(headers={"X-User-Id": "1"})) is True
    assert is_request_superuser(DummyRequest(headers={"jwt-sub": "1"})) is True
    assert is_request_superuser(DummyRequest(headers={"sub": "1"})) is True

    assert is_request_superuser(DummyRequest(headers={"X-Role": "user"})) is False
    assert is_request_superuser(DummyRequest(headers={"X-Role": "operator"})) is False
    assert is_request_superuser(DummyRequest(headers={})) is False


@pytest.mark.asyncio
async def test_get_internal_org_id_superuser_override():
    # 1. Superuser with X-Org-Id=1 and query org_id=339 -> 339
    req_su = DummyRequest(
        headers={"X-Role": "superuser", "X-Org-Id": "1"},
        query_params={"org_id": "339"},
    )
    assert await get_internal_org_id(req_su, True) == 339

    # 2. Superuser with X-Org-Id=1 and no query -> 1
    req_su_no_q = DummyRequest(
        headers={"X-Role": "superuser", "X-Org-Id": "1"},
        query_params={},
    )
    assert await get_internal_org_id(req_su_no_q, True) == 1

    # 3. Superuser with no header and query org_id=339 -> 339
    req_su_q_only = DummyRequest(
        headers={"X-Role": "superuser"},
        query_params={"org_id": "339"},
    )
    assert await get_internal_org_id(req_su_q_only, True) == 339


@pytest.mark.asyncio
async def test_get_internal_org_id_non_superuser_isolation():
    # 1. Non-superuser with X-Org-Id=1 and query org_id=339 -> strictly 1 (query ignored)
    req_user = DummyRequest(
        headers={"X-Role": "user", "X-Org-Id": "1"},
        query_params={"org_id": "339"},
    )
    assert await get_internal_org_id(req_user, True) == 1

    # 2. Non-superuser with X-Org-Id=77 and query org_id=339 -> strictly 77 (query ignored)
    req_tenant = DummyRequest(
        headers={"X-Role": "tenant_admin", "X-Org-Id": "77"},
        query_params={"org_id": "339"},
    )
    assert await get_internal_org_id(req_tenant, True) == 77


@pytest.mark.asyncio
async def test_get_internal_org_id_service_calls_and_validation():
    # 1. Service call with header -> 55
    req_svc_hdr = DummyRequest(headers={"X-Org-Id": "55"})
    assert await get_internal_org_id(req_svc_hdr, True) == 55

    # 2. Service call with query -> 55
    req_svc_query = DummyRequest(query_params={"org_id": "55"})
    assert await get_internal_org_id(req_svc_query, True) == 55

    # 3. Missing both -> 400
    req_empty = DummyRequest()
    with pytest.raises(HTTPException) as exc_info:
        await get_internal_org_id(req_empty, True)
    assert exc_info.value.status_code == 400

    # 4. Invalid int -> 400
    req_invalid = DummyRequest(headers={"X-Org-Id": "invalid"})
    with pytest.raises(HTTPException) as exc_info:
        await get_internal_org_id(req_invalid, True)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_get_internal_billing_org_id():
    # Superuser with query
    req_su = DummyRequest(
        headers={"X-Role": "superuser", "X-Org-Id": "1"},
        query_params={"org_id": "339"},
    )
    assert await get_internal_billing_org_id(req_su, True) == 339

    # Empty defaults to 0
    req_empty = DummyRequest()
    assert await get_internal_billing_org_id(req_empty, True) == 0


@pytest.mark.asyncio
async def test_internal_api_auth_and_operations(monkeypatch):
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
        # 1. Internal endpoints reject without secret
        resp_unauth = await ac.get("/api/internal/v1/devices/")
        assert resp_unauth.status_code == 403

        # 2. Internal endpoints reject without X-Org-Id
        resp_no_org = await ac.get(
            "/api/internal/v1/devices/",
            headers={"X-Internal-Service-Key": "secret123"},
        )
        assert resp_no_org.status_code == 400
        assert "Missing required 'X-Org-Id'" in resp_no_org.json()["detail"]

        # 3. Devices with valid headers
        with patch("core.services.devices.DeviceService.get_list", new_callable=AsyncMock) as mock_get_list:
            mock_get_list.return_value = []
            resp = await ac.get("/api/internal/v1/devices/", headers=headers)
            assert resp.status_code == 200
            assert resp.json() == []
            mock_get_list.assert_called_once_with(mock_get_list.call_args[0][0], 42, None)

        # 4. Devices with superuser role and query org_id=339 (should pass 339 to service)
        su_headers = {
            "X-Internal-Service-Key": "secret123",
            "X-Org-Id": "1",
            "X-Role": "superuser",
        }
        with patch("core.services.devices.DeviceService.get_list", new_callable=AsyncMock) as mock_get_list:
            mock_get_list.return_value = []
            resp = await ac.get("/api/internal/v1/devices/?org_id=339", headers=su_headers)
            assert resp.status_code == 200
            mock_get_list.assert_called_once_with(mock_get_list.call_args[0][0], 339, None)

        # 5. Devices with regular user role and query org_id=339 (should strictly pass 1 from header)
        user_headers = {
            "X-Internal-Service-Key": "secret123",
            "X-Org-Id": "1",
            "X-Role": "user",
        }
        with patch("core.services.devices.DeviceService.get_list", new_callable=AsyncMock) as mock_get_list:
            mock_get_list.return_value = []
            resp = await ac.get("/api/internal/v1/devices/?org_id=339", headers=user_headers)
            assert resp.status_code == 200
            mock_get_list.assert_called_once_with(mock_get_list.call_args[0][0], 1, None)

        # 6. Webhooks list with superuser override
        with patch("core.crud.webhook_repo.WebhookRepo.get_all_by_org", new_callable=AsyncMock) as mock_webhooks:
            mock_webhooks.return_value = []
            resp = await ac.get("/api/internal/v1/webhooks/?org_id=339", headers=su_headers)
            assert resp.status_code == 200
            mock_webhooks.assert_called_once_with(339)

    app.dependency_overrides.clear()
