import pytest
import httpx

from core.integrations import rmq_admin_api
from core.integrations.rmq_admin_api import RmqAdminApi


class DummyResponse:
    def __init__(self, status_code: int, payload, url: str):
        self.status_code = status_code
        self._payload = payload
        self.request = httpx.Request("GET", f"http://test/{url}")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"Client error '{self.status_code}' for url '{self.request.url}'",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )


class DummyAsyncClient:
    def __init__(self, *args, responses: dict[str, DummyResponse] | None = None, **kwargs):
        self._responses = responses or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str):
        response = self._responses.get(url)
        if response is None:
            raise AssertionError(f"Unexpected GET {url}")
        return response


@pytest.mark.asyncio
async def test_get_connection_uses_username_connections_payload(monkeypatch):
    responses = {
        "api/connections/username/SN_001": DummyResponse(
            200,
            [
                {
                    "user": "SN_001",
                    "connected_at": 1710000000,
                    "peer_host": "127.0.0.1",
                    "peer_cert_subject": "CN=SN_001",
                    "protocol": "mqtt",
                    "peer_cert_validity": "valid",
                    "client_properties": {"client_id": "12345678901234567890123"},
                },
                {
                    "user": "SN_001",
                    "connected_at": 1710000001,
                    "peer_host": "127.0.0.2",
                    "peer_cert_subject": "CN=SN_001-second",
                    "protocol": "mqtt",
                    "peer_cert_validity": "valid",
                    "client_properties": {"client_id": "ABCDEFGHIJKLMNO12345678"},
                },
            ],
            "api/connections/username/SN_001",
        ),
        "api/connections/username/SN_002": DummyResponse(
            200,
            [],
            "api/connections/username/SN_002",
        ),
    }

    monkeypatch.setattr(
        rmq_admin_api.httpx,
        "AsyncClient",
        lambda *args, **kwargs: DummyAsyncClient(*args, responses=responses, **kwargs),
    )

    devices = await RmqAdminApi.get_connection(["SN_001", "SN_002"])

    assert len(devices) == 2
    assert [device.user for device in devices] == ["SN_001", "SN_001"]
    assert [device.client_properties.client_id for device in devices] == [
        "12345678901234567890123",
        "ABCDEFGHIJKLMNO12345678",
    ]


@pytest.mark.asyncio
async def test_get_connection_keeps_other_devices_when_one_request_fails(monkeypatch):
    responses = {
        "api/connections/username/SN_FAIL": DummyResponse(
            500,
            {"error": "boom"},
            "api/connections/username/SN_FAIL",
        ),
        "api/connections/username/SN_OK": DummyResponse(
            200,
            [
                {
                    "user": "SN_OK",
                    "connected_at": 1710000100,
                    "peer_host": "127.0.0.10",
                    "peer_cert_subject": "CN=SN_OK",
                    "protocol": "mqtt",
                    "peer_cert_validity": "valid",
                    "client_properties": {"client_id": "ZYXWVUTSRQPONMLKJIHGFED"},
                }
            ],
            "api/connections/username/SN_OK",
        ),
    }

    monkeypatch.setattr(
        rmq_admin_api.httpx,
        "AsyncClient",
        lambda *args, **kwargs: DummyAsyncClient(*args, responses=responses, **kwargs),
    )

    devices = await RmqAdminApi.get_connection(["SN_FAIL", "SN_OK"])

    assert len(devices) == 1
    assert devices[0].user == "SN_OK"
    assert devices[0].client_properties.client_id == "ZYXWVUTSRQPONMLKJIHGFED"

