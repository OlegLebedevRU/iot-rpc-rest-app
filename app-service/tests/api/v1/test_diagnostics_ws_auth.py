from __future__ import annotations

from typing import cast

import pytest
from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from api.internal_v1 import diagnostics as diagnostics_api


class DummyWebSocket:
    def __init__(
        self,
        headers: dict[str, str],
        query_params: dict[str, str] | None = None,
    ) -> None:
        self.headers = headers
        self.query_params = query_params or {}
        self.accepted = False
        self.close_code: int | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int) -> None:
        self.close_code = code


@pytest.mark.asyncio
async def test_resolve_websocket_org_id_does_not_accept_api_key() -> None:
    websocket = DummyWebSocket({"x-api-key": "test"})

    assert (
        await diagnostics_api._resolve_websocket_org_id(cast(WebSocket, websocket))
        is None
    )


@pytest.mark.asyncio
async def test_resolve_websocket_org_id_from_forwarded_header() -> None:
    cases = [
        ({"X-Role": "superuser", "orgId": "42"}, {}, 42),
        ({"X-Role": "admin", "orgid": "43"}, {}, 43),
        ({"X-User-Id": "1", "orgId": "44"}, {}, 44),
        ({"jwt-role": "admin", "jwt-org": "45"}, {}, 45),
        ({"X-Role-Id": "1", "X-Org-Id": "46"}, {}, 46),
        ({"X-Role": "superuser"}, {"org_id": "47"}, 47),
        ({"X-Role": "superuser", "orgId": "bad"}, {}, None),
        ({"X-Role": "superuser"}, {}, None),
        ({"orgId": "42"}, {}, None),  # Rejected because not superuser
        ({}, {}, None),
    ]

    for headers, query_params, expected in cases:
        websocket = DummyWebSocket(headers, query_params=query_params)

        assert (
            await diagnostics_api._resolve_websocket_org_id(cast(WebSocket, websocket))
            == expected
        )


@pytest.mark.asyncio
async def test_is_websocket_device_allowed_checks_sn_and_org(monkeypatch) -> None:
    calls = []

    async def fake_get_device_id(*, session, sn, org_id):
        calls.append((session, sn, org_id))
        return 123

    monkeypatch.setattr(diagnostics_api.DeviceRepo, "get_device_id", fake_get_device_id)
    session = cast(AsyncSession, object())

    assert (
        await diagnostics_api._is_websocket_device_allowed(
            session, sn="SN001", org_id=7
        )
        is True
    )
    assert calls == [(session, "SN001", 7)]


@pytest.mark.asyncio
async def test_diagnostics_ws_rejects_missing_org_id_before_accept() -> None:
    websocket = DummyWebSocket({})

    await diagnostics_api.diagnostics_ws(
        cast(WebSocket, websocket), "SN001", cast(AsyncSession, object())
    )

    assert websocket.accepted is False
    assert websocket.close_code == status.WS_1008_POLICY_VIOLATION


@pytest.mark.asyncio
async def test_diagnostics_ws_rejects_foreign_device_before_accept(monkeypatch) -> None:
    async def fake_is_allowed(session, *, sn, org_id):
        return False

    monkeypatch.setattr(
        diagnostics_api, "_is_websocket_device_allowed", fake_is_allowed
    )
    websocket = DummyWebSocket({"X-Role": "superuser", "orgId": "7"})

    await diagnostics_api.diagnostics_ws(
        cast(WebSocket, websocket), "SN001", cast(AsyncSession, object())
    )

    assert websocket.accepted is False
    assert websocket.close_code == status.WS_1008_POLICY_VIOLATION
