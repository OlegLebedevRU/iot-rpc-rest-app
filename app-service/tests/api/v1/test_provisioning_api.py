import pytest
from httpx import ASGITransport, AsyncClient

from core.config import settings
from core.models import db_helper
from core.schemas.provisioning import TerminalProvisionResult, TerminalStatusResult
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

    async def fake_session_getter():
        yield object()

    app.dependency_overrides[db_helper.session_getter] = fake_session_getter
    monkeypatch.setattr(ProvisioningService, "provision_terminals", fake_provision)
    monkeypatch.setattr(ProvisioningService, "get_terminals_status", fake_status)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        # 1. Reject without auth
        resp = await ac.post(
            "/api/v1/provisioning/terminals",
            json={"device_id": 773, "sn": "a4b0000773c12345d230826", "org_id": 12},
        )
        assert resp.status_code == 403

        # 2. Allow with X-Internal-Service-Key
        headers = {"X-Internal-Service-Key": "secret123"}
        resp = await ac.post(
            "/api/v1/provisioning/terminals",
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
            "/api/v1/provisioning/terminals/status",
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

    app.dependency_overrides.clear()
