import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.crud.device_repo import DeviceRepo
from core.integrations.rmq_admin_api import RmqAdminApi
from core.services.rmq_admin import RmqAdmin
from typing import cast


@pytest.mark.asyncio
async def test_set_device_definitions_reconciles_all_db_devices(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_list(session):
        return ["SN_001", "", None, "SN_002"]

    async def fake_set_device_definitions(device_names, dry_run=False):
        captured["device_names"] = device_names
        captured["dry_run"] = dry_run
        return {"created": 0, "updated": 2, "skipped": 2, "errors": []}

    monkeypatch.setattr(DeviceRepo, "list", fake_list)
    monkeypatch.setattr(
        RmqAdminApi, "set_device_definitions", fake_set_device_definitions
    )

    result = await RmqAdmin.set_device_definitions(
        session=cast(AsyncSession, object()), dry_run=True
    )

    assert captured == {"device_names": ["SN_001", "SN_002"], "dry_run": True}
    assert result == {"created": 0, "updated": 2, "skipped": 2, "errors": []}


@pytest.mark.asyncio
async def test_set_device_definitions_returns_none_without_devices(monkeypatch):
    async def fake_list(session):
        return ["", None]

    async def fake_set_device_definitions(
        device_names, dry_run=False
    ):  # pragma: no cover
        raise AssertionError("RabbitMQ API must not be called without devices")

    monkeypatch.setattr(DeviceRepo, "list", fake_list)
    monkeypatch.setattr(
        RmqAdminApi, "set_device_definitions", fake_set_device_definitions
    )

    assert (
        await RmqAdmin.set_device_definitions(session=cast(AsyncSession, object()))
        is None
    )
