"""Tests for Leo4Client HTTP client."""
from __future__ import annotations
import pytest
import respx
import httpx

from leo4_mcp.client import Leo4Client, Leo4ApiError
from leo4_mcp.config import settings


@pytest.fixture
def client():
    c = Leo4Client()
    yield c


@pytest.fixture(autouse=True)
def _dry_off(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "allowed_device_ids", [])


@respx.mock
@pytest.mark.asyncio
async def test_get_success(client):
    respx.get("https://dev.leo4.ru/api/v1/device-tasks/test-id").mock(
        return_value=httpx.Response(200, json={"id": "test-id", "status": 3})
    )
    result = await client.get("/device-tasks/test-id")
    assert result["status"] == 3


@respx.mock
@pytest.mark.asyncio
async def test_401_raises(client):
    respx.post("https://dev.leo4.ru/api/v1/device-tasks/").mock(
        return_value=httpx.Response(401, json={"detail": "unauthorized"})
    )
    with pytest.raises(Leo4ApiError) as exc_info:
        await client.post("/device-tasks/", json={"device_id": 1})
    assert exc_info.value.status_code == 401


@respx.mock
@pytest.mark.asyncio
async def test_422_raises(client):
    respx.post("https://dev.leo4.ru/api/v1/device-tasks/").mock(
        return_value=httpx.Response(422, json={"detail": "validation error"})
    )
    with pytest.raises(Leo4ApiError) as exc_info:
        await client.post("/device-tasks/", json={})
    assert exc_info.value.status_code == 422


@respx.mock
@pytest.mark.asyncio
async def test_500_retries_and_raises(client, monkeypatch):
    monkeypatch.setattr(settings, "http_retries", 2)
    call_count = 0

    def handler(request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(500, text="Server Error")

    respx.post("https://dev.leo4.ru/api/v1/device-tasks/").mock(side_effect=handler)
    with pytest.raises(Leo4ApiError) as exc_info:
        await client.post("/device-tasks/", json={"device_id": 1})
    assert exc_info.value.status_code == 500
    assert call_count == 2
