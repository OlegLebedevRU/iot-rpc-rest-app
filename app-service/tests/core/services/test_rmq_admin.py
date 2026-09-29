import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.crud.device_repo import DeviceRepo
from core.integrations.rmq_admin_api import RmqAdminApi
from core.schemas.rmq_admin import DeviceConnectionDetails
from core.services.rmq_admin import RmqAdmin
from typing import cast


@pytest.mark.asyncio
async def test_set_device_definitions_reconciles_all_db_devices(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_list(session):
        return ["SN_001", "", None, "SN_002"]

    async def fake_list_blocked(session):
        return ["SN_002", "SN_BLOCKED"]

    async def fake_block_device_user(name):
        captured.setdefault("blocked", []).append(name)
        return True

    async def fake_set_device_definitions(device_names, dry_run=False):
        captured["device_names"] = device_names
        captured["dry_run"] = dry_run
        return {"created": 0, "updated": 2, "skipped": 2, "errors": []}

    monkeypatch.setattr(DeviceRepo, "list", fake_list)
    monkeypatch.setattr(DeviceRepo, "list_blocked", fake_list_blocked)
    monkeypatch.setattr(RmqAdminApi, "block_device_user", fake_block_device_user)
    monkeypatch.setattr(
        RmqAdminApi, "set_device_definitions", fake_set_device_definitions
    )

    result = await RmqAdmin.set_device_definitions(
        session=cast(AsyncSession, object()), dry_run=True
    )

    assert captured == {"device_names": ["SN_001"], "dry_run": True}
    assert result == {
        "created": 0,
        "updated": 2,
        "skipped": 2,
        "errors": [],
        "blocked_deleted": 0,
        "blocked_would_delete": 2,
    }


@pytest.mark.asyncio
async def test_set_device_definitions_returns_none_without_devices(monkeypatch):
    async def fake_list(session):
        return ["", None]

    async def fake_set_device_definitions(
        device_names, dry_run=False
    ):  # pragma: no cover
        raise AssertionError("RabbitMQ API must not be called without devices")

    monkeypatch.setattr(DeviceRepo, "list", fake_list)
    monkeypatch.setattr(DeviceRepo, "list_blocked", fake_list)
    monkeypatch.setattr(
        RmqAdminApi, "set_device_definitions", fake_set_device_definitions
    )

    assert (
        await RmqAdmin.set_device_definitions(session=cast(AsyncSession, object()))
        is None
    )


@pytest.mark.asyncio
async def test_recovery_deletes_blocked_user_before_restoring_active(monkeypatch):
    calls = []

    async def fake_list(session):
        return ["SN_ACTIVE", "SN_BLOCKED"]

    async def fake_list_blocked(session):
        return ["SN_BLOCKED"]

    async def fake_block(name):
        calls.append(("delete", name))
        return True

    async def fake_restore(names, dry_run=False):
        calls.append(("restore", names))
        return {"created": 0, "updated": 0, "skipped": 1, "errors": []}

    monkeypatch.setattr(DeviceRepo, "list", fake_list)
    monkeypatch.setattr(DeviceRepo, "list_blocked", fake_list_blocked)
    monkeypatch.setattr(RmqAdminApi, "block_device_user", fake_block)
    monkeypatch.setattr(RmqAdminApi, "set_device_definitions", fake_restore)

    result = await RmqAdmin.set_device_definitions(session=cast(AsyncSession, object()))

    assert calls == [("delete", "SN_BLOCKED"), ("restore", ["SN_ACTIVE"])]
    assert result["blocked_deleted"] == 1
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_rmq_admin_get_online_devices(monkeypatch):
    async def fake_get_connection(sn_arr):
        return [
            DeviceConnectionDetails.model_validate(
                {
                    "user": "SN_100",
                    "connected_at": 1700000000000,
                    "peer_host": "127.0.0.1",
                    "peer_port": 50000,
                    "protocol": "MQTT",
                    "peer_cert_subject": "CN=SN_100",
                    "peer_cert_validity": "valid",
                    "client_properties": {"client_id": "SN_100"},
                }
            )
        ]

    monkeypatch.setattr(RmqAdminApi, "get_connection", fake_get_connection)
    res = await RmqAdmin.get_online_devices(["SN_100", "SN_200"])
    assert len(res) == 1
    assert res[0].user == "SN_100"
