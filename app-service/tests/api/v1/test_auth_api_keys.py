from __future__ import annotations

from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.api_v1.api_depends import get_org_id_dependency
from api.internal_v1.internal_depends import (
    verify_internal_service_auth,
    get_internal_org_id,
    get_internal_billing_org_id,
)
from core.config import settings
from core.services.provisioning import ProvisioningService


def _make_request(headers: dict[str, str] | None = None, query: str = "") -> Request:
    raw_headers = []
    if headers:
        for k, v in headers.items():
            raw_headers.append((k.lower().encode("latin-1"), v.encode("latin-1")))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "query_string": query.encode("latin-1"),
        "headers": raw_headers,
        "state": {},
    }
    return Request(scope)


# ==========================================
# Public API Tests (get_org_id_dependency)
# ==========================================


@pytest.mark.asyncio
async def test_get_org_id_via_active_db_api_key():
    req = _make_request({"x-api-key": "test_valid_key"})
    session = AsyncMock()
    session.scalar.return_value = 42

    org_id = await get_org_id_dependency(
        request=req,
        session=session,
        api_key="test_valid_key",
    )
    assert org_id == 42
    assert req.state.billing_org_id == 42


@pytest.mark.asyncio
async def test_get_org_id_via_upper_header_fallback():
    req = _make_request({"X-API-Key": "test_valid_key"})
    session = AsyncMock()
    session.scalar.return_value = 42

    org_id = await get_org_id_dependency(
        request=req,
        session=session,
        api_key=None,
    )
    assert org_id == 42


@pytest.mark.asyncio
async def test_get_org_id_via_authorization_api_key_header():
    req = _make_request({"Authorization": "ApiKey test_auth_key"})
    session = AsyncMock()
    session.scalar.return_value = 55

    org_id = await get_org_id_dependency(
        request=req,
        session=session,
        api_key=None,
    )
    assert org_id == 55


@pytest.mark.asyncio
async def test_get_org_id_via_static_settings_fallback(monkeypatch):
    monkeypatch.setattr(settings.auth, "api_keys_raw", "test:1")
    req = _make_request({"x-api-key": "test:1"})
    session = AsyncMock()
    session.scalar.return_value = None  # Not in DB

    # APP_CONFIG__AUTH__API_KEYS is initialized to {"test": 1} in tests/conftest
    org_id = await get_org_id_dependency(
        request=req,
        session=session,
        api_key="test",
    )
    assert org_id == 1


@pytest.mark.asyncio
async def test_get_org_id_invalid_api_key_raises_401():
    req = _make_request({"x-api-key": "invalid_key"})
    session = AsyncMock()
    session.scalar.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await get_org_id_dependency(
            request=req,
            session=session,
            api_key="invalid_key",
        )
    assert exc_info.value.status_code == 401
    assert "Invalid or inactive API Key" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_org_id_missing_api_key_raises_401():
    req = _make_request({})
    session = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_org_id_dependency(
            request=req,
            session=session,
            api_key=None,
        )
    assert exc_info.value.status_code == 401
    assert "Missing or invalid authentication credentials" in exc_info.value.detail


# ==========================================
# Internal API Tests (internal_depends.py)
# ==========================================


@pytest.mark.asyncio
async def test_verify_internal_service_auth_header(monkeypatch):
    monkeypatch.setattr(settings.auth, "internal_service_key", "secret_123")
    req = _make_request({"X-Internal-Service-Key": "secret_123"})
    assert await verify_internal_service_auth(req) is True


@pytest.mark.asyncio
async def test_verify_internal_service_auth_bearer(monkeypatch):
    monkeypatch.setattr(settings.auth, "internal_service_key", "secret_123")
    req = _make_request({"Authorization": "Bearer secret_123"})
    assert await verify_internal_service_auth(req) is True


@pytest.mark.asyncio
async def test_verify_internal_service_auth_invalid(monkeypatch):
    monkeypatch.setattr(settings.auth, "internal_service_key", "secret_123")
    req = _make_request({"X-Internal-Service-Key": "wrong_key"})
    with pytest.raises(HTTPException) as exc_info:
        await verify_internal_service_auth(req)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_get_internal_org_id_via_header():
    req = _make_request({"X-Org-Id": "100"})
    org_id = await get_internal_org_id(req, _=True)
    assert org_id == 100
    assert req.state.billing_org_id == 100


@pytest.mark.asyncio
async def test_get_internal_org_id_via_query():
    req = _make_request(query="org_id=200")
    org_id = await get_internal_org_id(req, _=True)
    assert org_id == 200


@pytest.mark.asyncio
async def test_get_internal_org_id_missing():
    req = _make_request({})
    with pytest.raises(HTTPException) as exc_info:
        await get_internal_org_id(req, _=True)
    assert exc_info.value.status_code == 400
    assert "Missing required 'X-Org-Id'" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_internal_org_id_invalid_int():
    req = _make_request({"X-Org-Id": "not_an_int"})
    with pytest.raises(HTTPException) as exc_info:
        await get_internal_org_id(req, _=True)
    assert exc_info.value.status_code == 400
    assert "must be a valid integer" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_internal_billing_org_id_default_zero():
    req = _make_request({})
    org_id = await get_internal_billing_org_id(req, _=True)
    assert org_id == 0


def test_mask_api_key_utility():
    assert ProvisioningService.mask_api_key("12345678") == "******78"
    assert ProvisioningService.mask_api_key("leo4_sec_98f12a34") == "leo4*********2a34"
    assert ProvisioningService.mask_api_key("abc") == "*bc"
    assert ProvisioningService.mask_api_key("") == ""
