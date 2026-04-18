"""Tests for event tools."""
from __future__ import annotations
import pytest
import respx
import httpx

from leo4_mcp.config import settings
from leo4_mcp.tools.events import get_recent_events, poll_device_event


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "allowed_device_ids", [])
    import leo4_mcp.client as c_mod
    c_mod._client = None


@respx.mock
@pytest.mark.asyncio
async def test_get_recent_events():
    respx.get("https://dev.leo4.ru/api/v1/device-events/fields/").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"value": 5, "created_at": "2026-01-01T00:00:00Z", "interval_sec": 10}
            ],
        )
    )
    result = await get_recent_events(device_id=4619, event_type_code=13, tag=304)
    assert len(result) == 1
    assert result[0]["value"] == 5


@respx.mock
@pytest.mark.asyncio
async def test_poll_device_event_found():
    respx.get("https://dev.leo4.ru/api/v1/device-events/fields/").mock(
        return_value=httpx.Response(
            200,
            json=[{"value": 5, "created_at": "2026-01-01T00:00:00Z", "interval_sec": 5}],
        )
    )
    result = await poll_device_event(
        device_id=4619,
        event_type_code=13,
        tag=304,
        expected_value=5,
        timeout_s=10,
    )
    assert result["confirmed"] is True
    assert result["event"]["value"] == 5


@respx.mock
@pytest.mark.asyncio
async def test_poll_device_event_timeout(monkeypatch):
    # Return empty list always → timeout
    respx.get("https://dev.leo4.ru/api/v1/device-events/fields/").mock(
        return_value=httpx.Response(200, json=[])
    )

    async def _noop(_):
        pass

    import asyncio
    monkeypatch.setattr(asyncio, "sleep", _noop)

    result = await poll_device_event(
        device_id=4619,
        event_type_code=13,
        tag=304,
        expected_value=5,
        timeout_s=1,
    )
    assert result["confirmed"] is False


@pytest.mark.asyncio
async def test_dry_run_events(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", True)
    result = await get_recent_events(device_id=4619)
    assert isinstance(result, list)
    assert len(result) > 0
