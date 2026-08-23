from datetime import datetime
from typing import cast
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.crud.device_repo import DeviceRepo
from core.integrations.rmq_admin_api import RmqAdminApi
from core.schemas.provisioning import (
    TerminalProvisionRequest,
)
from core.services.provisioning import ProvisioningService


@pytest.mark.asyncio
async def test_provision_terminals_success(monkeypatch):
    captured_db = []
    captured_rmq = []

    async def fake_provision_terminals(session, data):
        captured_db.extend(data)

    async def fake_set_device_definitions(device_names, dry_run=False):
        captured_rmq.extend(device_names)
        return {"created": 1, "updated": 0, "skipped": 0, "errors": []}

    async def fake_get_connection(sns):
        return []

    monkeypatch.setattr(DeviceRepo, "provision_terminals", fake_provision_terminals)
    monkeypatch.setattr(
        RmqAdminApi, "set_device_definitions", fake_set_device_definitions
    )
    monkeypatch.setattr(RmqAdminApi, "get_connection", fake_get_connection)

    requests = [
        TerminalProvisionRequest(
            device_id=773,
            sn="a4b0000773c12345d230826",
            org_id=12,
            name="Test Terminal 773",
            tags={"source": "etranprocessing"},
        )
    ]

    results = await ProvisioningService.provision_terminals(
        session=cast(AsyncSession, object()),
        terminals=requests,
    )

    assert len(results) == 1
    assert results[0].device_id == 773
    assert results[0].sn == "a4b0000773c12345d230826"
    assert results[0].org_id == 12
    assert results[0].success is True
    assert results[0].rmq_user_status == "ok"
    assert results[0].is_online is False
    assert len(captured_db) == 1
    assert captured_db[0]["device_id"] == 773
    assert captured_rmq == ["a4b0000773c12345d230826"]


@pytest.mark.asyncio
async def test_get_terminals_status(monkeypatch):
    async def fake_get_status(session, device_ids):
        return [
            {
                "device_id": 773,
                "sn": "a4b0000773c12345d230826",
                "org_id": 12,
                "is_provisioned": True,
                "is_online": True,
                "connected_at": datetime(2026, 8, 23, 12, 0, 0),
                "checked_at": datetime(2026, 8, 23, 12, 30, 0),
            },
            {
                "device_id": 999,
                "sn": None,
                "org_id": None,
                "is_provisioned": False,
                "is_online": False,
                "connected_at": None,
                "checked_at": None,
            },
        ]

    monkeypatch.setattr(
        DeviceRepo, "get_terminals_status_by_device_ids", fake_get_status
    )

    statuses = await ProvisioningService.get_terminals_status(
        session=cast(AsyncSession, object()),
        device_ids=[773, 999],
    )

    assert len(statuses) == 2
    assert statuses[0].device_id == 773
    assert statuses[0].is_provisioned is True
    assert statuses[0].is_online is True
    assert statuses[1].device_id == 999
    assert statuses[1].is_provisioned is False
    assert statuses[1].is_online is False
