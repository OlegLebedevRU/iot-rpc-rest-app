from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch

from core.config import settings
from core.models import db_helper
from main import main_app as app


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

        # 4. Webhooks list with valid headers
        with patch("core.crud.webhook_repo.WebhookRepo.get_all_by_org", new_callable=AsyncMock) as mock_webhooks:
            mock_webhooks.return_value = []
            resp = await ac.get("/api/internal/v1/webhooks/", headers=headers)
            assert resp.status_code == 200
            assert resp.json() == []

    app.dependency_overrides.clear()
