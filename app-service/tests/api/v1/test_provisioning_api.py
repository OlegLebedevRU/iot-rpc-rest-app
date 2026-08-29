import pytest
from httpx import ASGITransport, AsyncClient

from datetime import datetime, UTC
from core.config import settings
from core.models import db_helper
from core.schemas.provisioning import (
    OrgApiKeyResponse,
    TerminalProvisionResult,
    TerminalStatusResult,
)
from core.services.provisioning import ProvisioningService
from main import main_app as app


@pytest.mark.asyncio
async def test_provisioning_api_auth_and_flow(monkeypatch):
    monkeypatch.setattr(settings.auth, "internal_service_key", "secret123")

    async def fake_provision(session, terminals):
        return [
            TerminalProvisionResult(
                device_id=t.device_id,
                sn=t.sn,
                org_id=t.org_id,
                success=True,
                rmq_user_status="ok",
                is_online=False,
            )
            for t in terminals
        ]

    async def fake_status(session, device_ids):
        return [
            TerminalStatusResult(
                device_id=d_id,
                sn="a4b0000773c12345d230826" if d_id == 773 else None,
                org_id=12 if d_id == 773 else None,
                is_provisioned=d_id == 773,
                is_online=False,
            )
            for d_id in device_ids
        ]

    now = datetime.now(tz=UTC)

    async def fake_provision_api_key(session, request):
        return OrgApiKeyResponse(
            org_id=request.org_id,
            api_key=request.api_key,
            name=request.name,
            is_active=request.is_active,
            created_at=now,
            updated_at=now,
        )

    async def fake_get_api_key(session, org_id, mask=False):
        if org_id == 12:
            key = "leo4_sec_98f12a34"
            if mask:
                key = ProvisioningService.mask_api_key(key)
            return OrgApiKeyResponse(
                org_id=12,
                api_key=key,
                name="Test Key",
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        return None

    async def fake_delete_api_key(session, org_id):
        return org_id == 12

    async def fake_session_getter():
        yield object()

    app.dependency_overrides[db_helper.session_getter] = fake_session_getter
    monkeypatch.setattr(ProvisioningService, "provision_terminals", fake_provision)
    monkeypatch.setattr(ProvisioningService, "get_terminals_status", fake_status)
    monkeypatch.setattr(ProvisioningService, "provision_org_api_key", fake_provision_api_key)
    monkeypatch.setattr(ProvisioningService, "get_org_api_key", fake_get_api_key)
    monkeypatch.setattr(ProvisioningService, "delete_org_api_key", fake_delete_api_key)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        # 1. Reject without auth
        resp = await ac.post(
            "/api/internal/v1/provisioning/terminals",
            json={"device_id": 773, "sn": "a4b0000773c12345d230826", "org_id": 12},
        )
        assert resp.status_code == 403

        # 2. Allow with X-Internal-Service-Key
        headers = {"X-Internal-Service-Key": "secret123"}
        resp = await ac.post(
            "/api/internal/v1/provisioning/terminals",
            headers=headers,
            json={"device_id": 773, "sn": "a4b0000773c12345d230826", "org_id": 12},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["device_id"] == 773
        assert data["success"] is True
        assert data["rmq_user_status"] == "ok"

        # 3. Query status
        status_resp = await ac.post(
            "/api/internal/v1/provisioning/terminals/status",
            headers=headers,
            json={"device_ids": [773, 999]},
        )
        assert status_resp.status_code == 200
        statuses = status_resp.json()["statuses"]
        assert len(statuses) == 2
        assert statuses[0]["device_id"] == 773
        assert statuses[0]["is_provisioned"] is True
        assert statuses[1]["device_id"] == 999
        assert statuses[1]["is_provisioned"] is False

        # 4. Provision API key
        key_resp = await ac.post(
            "/api/internal/v1/provisioning/api-keys",
            headers=headers,
            json={
                "org_id": 12,
                "api_key": "leo4_sec_98f12a34",
                "name": "Test Key",
                "is_active": True,
            },
        )
        assert key_resp.status_code == 200
        key_data = key_resp.json()
        assert key_data["org_id"] == 12
        assert key_data["api_key"] == "leo4_sec_98f12a34"
        assert key_data["is_active"] is True

        # 5. Get API key unmasked
        get_resp = await ac.get(
            "/api/internal/v1/provisioning/api-keys/12",
            headers=headers,
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["api_key"] == "leo4_sec_98f12a34"

        # 6. Get API key masked
        get_masked_resp = await ac.get(
            "/api/internal/v1/provisioning/api-keys/12?mask=true",
            headers=headers,
        )
        assert get_masked_resp.status_code == 200
        assert get_masked_resp.json()["api_key"] == "leo4*********2a34"

        # 7. Get non-existent API key -> 404
        get_404 = await ac.get(
            "/api/internal/v1/provisioning/api-keys/999",
            headers=headers,
        )
        assert get_404.status_code == 404

        # 8. Delete API key
        del_resp = await ac.delete(
            "/api/internal/v1/provisioning/api-keys/12",
            headers=headers,
        )
        assert del_resp.status_code == 200
        assert del_resp.json() == {"status": "deleted", "org_id": 12}

        # 9. Delete non-existent API key -> 404
        del_404 = await ac.delete(
            "/api/internal/v1/provisioning/api-keys/999",
            headers=headers,
        )
        assert del_404.status_code == 404

    app.dependency_overrides.clear()
