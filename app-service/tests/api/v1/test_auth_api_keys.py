from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, UTC
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.api_v1.api_depends import get_org_id_dependency
from core.config import settings
from core.schemas.provisioning import OrgApiKeyProvisionRequest
from core.services.provisioning import ProvisioningService


def _make_request(headers: dict[str, str] | None = None) -> Request:
    raw_headers = []
    if headers:
        for k, v in headers.items():
            raw_headers.append((k.lower().encode("latin-1"), v.encode("latin-1")))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "headers": raw_headers,
        "state": {},
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_get_org_id_via_active_db_api_key():
    req = _make_request({"X-API-Key": "test_valid_key"})
    session = AsyncMock()
    session.scalar.return_value = 42

    org_id = await get_org_id_dependency(
        request=req,
        session=session,
        api_key_upper="test_valid_key",
        api_key_lower=None,
        internal_service_key=None,
        auth_header=None,
        org_id_str=None,
        x_org_id_str=None,
        role_header=None,
        role_id_header=None,
        jwt_role_header=None,
        org_id_query=None,
    )
    assert org_id == 42
    assert req.state.billing_org_id == 42


@pytest.mark.asyncio
async def test_get_org_id_via_authorization_api_key_header():
    req = _make_request({"Authorization": "ApiKey test_auth_key"})
    session = AsyncMock()
    session.scalar.return_value = 55

    org_id = await get_org_id_dependency(
        request=req,
        session=session,
        api_key_upper=None,
        api_key_lower=None,
        internal_service_key=None,
        auth_header="ApiKey test_auth_key",
        org_id_str=None,
        x_org_id_str=None,
        role_header=None,
        role_id_header=None,
        jwt_role_header=None,
        org_id_query=None,
    )
    assert org_id == 55


@pytest.mark.asyncio
async def test_get_org_id_invalid_api_key_raises_401():
    req = _make_request({"X-API-Key": "invalid_key"})
    session = AsyncMock()
    session.scalar.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await get_org_id_dependency(
            request=req,
            session=session,
            api_key_upper="invalid_key",
            api_key_lower=None,
            internal_service_key=None,
            auth_header=None,
            org_id_str=None,
            x_org_id_str=None,
            role_header=None,
            role_id_header=None,
            jwt_role_header=None,
            org_id_query=None,
        )
    assert exc_info.value.status_code == 401
    assert "Invalid or inactive API Key" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_org_id_via_internal_service_key(monkeypatch):
    monkeypatch.setattr(settings.auth, "internal_service_key", "super_internal_secret")
    req = _make_request({"X-Internal-Service-Key": "super_internal_secret"})
    session = AsyncMock()

    org_id = await get_org_id_dependency(
        request=req,
        session=session,
        api_key_upper=None,
        api_key_lower=None,
        internal_service_key="super_internal_secret",
        auth_header=None,
        org_id_str="88",
        x_org_id_str=None,
        role_header=None,
        role_id_header=None,
        jwt_role_header=None,
        org_id_query=None,
    )
    assert org_id == 88


@pytest.mark.asyncio
async def test_get_org_id_via_superuser_headers():
    req = _make_request({"X-Role": "superuser", "orgId": "99"})
    session = AsyncMock()

    org_id = await get_org_id_dependency(
        request=req,
        session=session,
        api_key_upper=None,
        api_key_lower=None,
        internal_service_key=None,
        auth_header=None,
        org_id_str="99",
        x_org_id_str=None,
        role_header="superuser",
        role_id_header=None,
        jwt_role_header=None,
        org_id_query=None,
    )
    assert org_id == 99


@pytest.mark.asyncio
async def test_get_org_id_missing_all_credentials_raises_401():
    req = _make_request({})
    session = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_org_id_dependency(
            request=req,
            session=session,
            api_key_upper=None,
            api_key_lower=None,
            internal_service_key=None,
            auth_header=None,
            org_id_str=None,
            x_org_id_str=None,
            role_header=None,
            role_id_header=None,
            jwt_role_header=None,
            org_id_query=None,
        )
    assert exc_info.value.status_code == 401


def test_mask_api_key_utility():
    assert ProvisioningService.mask_api_key("12345678") == "******78"
    assert ProvisioningService.mask_api_key("leo4_sec_98f12a34") == "leo4*********2a34"
    assert ProvisioningService.mask_api_key("abc") == "*bc"
    assert ProvisioningService.mask_api_key("") == ""
