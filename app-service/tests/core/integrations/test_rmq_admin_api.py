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
    def __init__(
        self,
        *args,
        responses: dict[str, DummyResponse] | None = None,
        put_responses: dict[str, DummyResponse] | None = None,
        put_calls: list[tuple[str, dict]] | None = None,
        **kwargs,
    ):
        self._responses = responses or {}
        self._put_responses = put_responses or {}
        self._put_calls = put_calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str):
        response = self._responses.get(url)
        if response is None:
            raise AssertionError(f"Unexpected GET {url}")
        return response

    async def put(self, url: str, json: dict):
        if self._put_calls is not None:
            self._put_calls.append((url, json))
        return self._put_responses.get(url, DummyResponse(204, None, url))


@pytest.mark.asyncio
async def test_get_connection_uses_username_connections_payload(monkeypatch):
    responses = {
        "api/connections/username/SN_001": DummyResponse(
            200,
            [
                {
                    "name": "127.0.0.1:50000 -> 172.18.0.2:8883",
                    "vhost": "/",
                    "user": "SN_001",
                },
                {
                    "name": "127.0.0.2:50001 -> 172.18.0.2:8883",
                    "vhost": "/",
                    "user": "SN_001",
                },
            ],
            "api/connections/username/SN_001",
        ),
        "api/connections/username/SN_002": DummyResponse(
            200,
            [],
            "api/connections/username/SN_002",
        ),
        "api/connections/127.0.0.1%3A50000%20-%3E%20172.18.0.2%3A8883": DummyResponse(
            200,
            {
                "name": "127.0.0.1:50000 -> 172.18.0.2:8883",
                "user": "SN_001",
                "connected_at": 1710000000,
                "peer_host": "127.0.0.1",
                "peer_cert_subject": "CN=SN_001",
                "protocol": "mqtt",
                "peer_cert_validity": "valid",
                "client_properties": {"client_id": "12345678901234567890123"},
            },
            "api/connections/127.0.0.1%3A50000%20-%3E%20172.18.0.2%3A8883",
        ),
        "api/connections/127.0.0.2%3A50001%20-%3E%20172.18.0.2%3A8883": DummyResponse(
            200,
            {
                "name": "127.0.0.2:50001 -> 172.18.0.2:8883",
                "user": "SN_001",
                "connected_at": 1710000001,
                "peer_host": "127.0.0.2",
                "peer_cert_subject": "CN=SN_001-second",
                "protocol": "mqtt",
                "peer_cert_validity": "valid",
                "client_properties": {"client_id": "ABCDEFGHIJKLMNO12345678"},
            },
            "api/connections/127.0.0.2%3A50001%20-%3E%20172.18.0.2%3A8883",
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
            200,
            [
                {
                    "name": "10.0.0.1:12345 -> 172.18.0.2:8883",
                    "vhost": "/",
                    "user": "SN_FAIL",
                }
            ],
            "api/connections/username/SN_FAIL",
        ),
        "api/connections/username/SN_OK": DummyResponse(
            200,
            [
                {
                    "name": "127.0.0.10:54321 -> 172.18.0.2:8883",
                    "vhost": "/",
                    "user": "SN_OK",
                }
            ],
            "api/connections/username/SN_OK",
        ),
        "api/connections/10.0.0.1%3A12345%20-%3E%20172.18.0.2%3A8883": DummyResponse(
            404,
            {"error": "not_found"},
            "api/connections/10.0.0.1%3A12345%20-%3E%20172.18.0.2%3A8883",
        ),
        "api/connections/127.0.0.10%3A54321%20-%3E%20172.18.0.2%3A8883": DummyResponse(
            200,
            {
                "name": "127.0.0.10:54321 -> 172.18.0.2:8883",
                "user": "SN_OK",
                "connected_at": 1710000100,
                "peer_host": "127.0.0.10",
                "peer_cert_subject": "CN=SN_OK",
                "protocol": "mqtt",
                "peer_cert_validity": "valid",
                "client_properties": {"client_id": "ZYXWVUTSRQPONMLKJIHGFED"},
            },
            "api/connections/127.0.0.10%3A54321%20-%3E%20172.18.0.2%3A8883",
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


@pytest.mark.asyncio
async def test_set_device_definitions_repairs_acl_for_existing_user(monkeypatch):
    responses = {
        "api/users/SN_EXIST": DummyResponse(
            200,
            {"name": "SN_EXIST", "tags": ["device"]},
            "api/users/SN_EXIST",
        ),
        "api/permissions/%2F/SN_EXIST": DummyResponse(
            404,
            {"error": "not_found"},
            "api/permissions/%2F/SN_EXIST",
        ),
        "api/topic-permissions/%2F/SN_EXIST": DummyResponse(
            200,
            [{"exchange": "amq.topic", "write": "^old$", "read": "^old$"}],
            "api/topic-permissions/%2F/SN_EXIST",
        ),
    }
    put_calls: list[tuple[str, dict]] = []

    monkeypatch.setattr(
        rmq_admin_api.httpx,
        "AsyncClient",
        lambda *args, **kwargs: DummyAsyncClient(
            *args, responses=responses, put_calls=put_calls, **kwargs
        ),
    )

    result = await RmqAdminApi.set_device_definitions(["SN_EXIST"])

    assert result == {
        "created": 0,
        "updated": 2,
        "skipped": 1,
        "would_create": 0,
        "would_update": 0,
        "errors": [],
    }
    assert put_calls == [
        (
            "api/permissions/%2F/SN_EXIST",
            {"configure": ".*", "write": ".*", "read": ".*"},
        ),
        (
            "api/topic-permissions/%2F/SN_EXIST",
            {
                "exchange": "amq.topic",
                "write": "^dev.{client_id}.*",
                "read": "^srv.{client_id}.*",
            },
        ),
    ]
