import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import Response

from core import settings
from core.integrations.rmq_admin_api import (
    RmqAdminApi,
    is_ignored_or_service_identity,
    extract_device_sn_from_conn,
    IGNORED_USERS,
)
from core.services.devices import DeviceService, extract_device_sn
from core.services.rmq_admin import RmqAdmin


def test_is_ignored_or_service_identity_matches():
    """Verify system users, service users and prefixes are correctly detected."""
    # 1. System users
    for user in ["guest", "admin", "user", "internal", "root", "anonymous", "null", "none", "etran_service"]:
        assert is_ignored_or_service_identity(user) is True
        assert is_ignored_or_service_identity(user.upper()) is True
        assert is_ignored_or_service_identity(f"  {user}  ") is True

    # 2. Service prefixes
    assert is_ignored_or_service_identity("etran") is True
    assert is_ignored_or_service_identity("etran_processing_1") is True
    assert is_ignored_or_service_identity("ETRAN_WORKER") is True
    assert is_ignored_or_service_identity("menubuilder") is True
    assert is_ignored_or_service_identity("menubuilder-backend-prod") is True

    # 3. None or empty
    assert is_ignored_or_service_identity(None) is True
    assert is_ignored_or_service_identity("") is True
    assert is_ignored_or_service_identity("   ") is True

    # 4. Valid device SNs
    assert is_ignored_or_service_identity("SN12345678") is False
    assert is_ignored_or_service_identity("a3b0000000c10221d290825") is False
    assert is_ignored_or_service_identity("device_terminal_01") is False


def test_extract_device_sn_and_from_conn():
    """Verify extract_device_sn and extract_device_sn_from_conn filter out service identities."""
    # Service connections -> None
    assert extract_device_sn_from_conn({"user": "etran_service"}) is None
    assert extract_device_sn_from_conn({"user": "user", "client_properties": {"client_id": "menubuilder-1"}}) is None
    assert extract_device_sn({"user": "etran_processing_1"}, {}) is None
    assert extract_device_sn({"user": ""}, {"client_id": "menubuilder-worker"}) is None

    # Valid device connections -> SN
    assert extract_device_sn_from_conn({"user": "SN_123456"}) == "SN_123456"
    assert extract_device_sn_from_conn({"user": "guest", "client_properties": {"client_id": "SN_7890"}}) == "SN_7890"
    assert extract_device_sn({"user": "a3b0000000c10221d290825"}, {}) == "a3b0000000c10221d290825"
    assert extract_device_sn({"user": ""}, {"client_id": "a3b0000000c10221d290825"}) == "a3b0000000c10221d290825"


@pytest.mark.asyncio
async def test_handle_connection_event_ignores_service_users():
    """Verify handle_connection_event completely ignores service connections without DB queries."""
    mock_session = AsyncMock()
    res = await DeviceService.handle_connection_event(
        session=mock_session,
        routing_key="connection.created",
        payload={"user": "etran_service", "name": "127.0.0.1:12345 -> 127.0.0.1:1883"},
        headers={},
    )
    assert res is False
    mock_session.execute.assert_not_called()
    mock_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_block_device_user_protection_for_system_and_service_accounts():
    """Verify block_device_user refuses to block system and service accounts."""
    for protected in ["guest", "user", "admin", "etran_service", "menubuilder-prod"]:
        res = await RmqAdminApi.block_device_user(protected)
        assert res is False


@pytest.mark.asyncio
async def test_reconcile_service_definitions(monkeypatch):
    """Verify reconcile_service_definitions queries and updates etran_service permissions if needed."""
    get_calls = []
    put_calls = []

    async def fake_get_json_or_none(client, path):
        get_calls.append(path)
        if "api/users/etran_service" in path:
            return {"name": "etran_service"}
        if "api/permissions" in path:
            # Old permissions that need update
            return {"configure": "", "write": ".*", "read": ".*"}
        if "api/topic-permissions" in path:
            # Topic perms matching
            return [
                {
                    "exchange": "amq.topic",
                    "write": "^(dev\\..*\\.gauge\\..*|telemetry\\..*)",
                    "read": "^(dev\\..*\\.gauge\\..*|telemetry\\..*)",
                }
            ]
        return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def put(self, path, json=None):
            put_calls.append((path, json))
            resp = MagicMock(spec=Response)
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            return resp

    monkeypatch.setattr(RmqAdminApi, "_get_json_or_none", fake_get_json_or_none)
    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: FakeClient())

    result = await RmqAdminApi.reconcile_service_definitions(dry_run=False)

    assert result["updated"] == 1
    assert any("api/permissions/%2F/etran_service" in call[0] for call in put_calls)
    perm_payload = next(call[1] for call in put_calls if "api/permissions/%2F/etran_service" in call[0])
    assert perm_payload["configure"] == "^(mqtt-subscription-.*|telemetry\\..*)"
