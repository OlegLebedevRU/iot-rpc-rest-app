"""Tests for composite tools, especially open_cell_and_confirm."""
from __future__ import annotations
import pytest
import respx
import httpx

from leo4_mcp.config import settings
from leo4_mcp.tools.composite import open_cell_and_confirm, mass_activate, reboot_device


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "allowed_device_ids", [])
    import leo4_mcp.client as c_mod
    c_mod._client = None


@respx.mock
@pytest.mark.asyncio
async def test_open_cell_and_confirm_success():
    # Step 1: create task
    respx.post("https://dev.leo4.ru/api/v1/device-tasks/").mock(
        return_value=httpx.Response(
            200, json={"id": "task-open-1", "created_at": 1712345678}
        )
    )
    # Step 2: get task status → DONE
    respx.get("https://dev.leo4.ru/api/v1/device-tasks/task-open-1").mock(
        return_value=httpx.Response(
            200,
            json={"id": "task-open-1", "status": 3, "status_name": "DONE"},
        )
    )
    # Step 3: poll event → cell 5 confirmed
    respx.get("https://dev.leo4.ru/api/v1/device-events/fields/").mock(
        return_value=httpx.Response(
            200,
            json=[{"value": 5, "created_at": "2026-01-01T00:00:00Z", "interval_sec": 8}],
        )
    )

    result = await open_cell_and_confirm(device_id=4619, cell_number=5, timeout_s=10)

    assert result["task"]["id"] == "task-open-1"
    assert result["delivery"]["status"] == 3
    assert result["physical_confirmation"]["confirmed"] is True
    assert result["physical_confirmation"]["event"]["value"] == 5


@respx.mock
@pytest.mark.asyncio
async def test_open_cell_and_confirm_timeout(monkeypatch):
    async def _noop(_):
        pass

    import asyncio
    monkeypatch.setattr(asyncio, "sleep", _noop)

    respx.post("https://dev.leo4.ru/api/v1/device-tasks/").mock(
        return_value=httpx.Response(200, json={"id": "task-open-2", "created_at": 1})
    )
    respx.get("https://dev.leo4.ru/api/v1/device-tasks/task-open-2").mock(
        return_value=httpx.Response(
            200, json={"id": "task-open-2", "status": 3, "status_name": "DONE"}
        )
    )
    respx.get("https://dev.leo4.ru/api/v1/device-events/fields/").mock(
        return_value=httpx.Response(200, json=[])
    )

    result = await open_cell_and_confirm(device_id=4619, cell_number=7, timeout_s=1)

    assert result["physical_confirmation"]["confirmed"] is False


@respx.mock
@pytest.mark.asyncio
async def test_mass_activate_parallel():
    call_count = 0

    async def handler(request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"id": f"task-{call_count}", "created_at": 1})

    respx.post("https://dev.leo4.ru/api/v1/device-tasks/").mock(side_effect=handler)

    result = await mass_activate(
        device_ids=[4619, 4620, 4621],
        method_code=20,
        payload={"dt": [{"mt": 0}]},
    )
    assert result["total"] == 3
    assert result["success"] == 3
    assert result["failed"] == 0


@respx.mock
@pytest.mark.asyncio
async def test_mass_activate_partial_failure(monkeypatch):
    import json as _json
    import leo4_mcp.client as c_mod
    monkeypatch.setattr(c_mod.settings, "http_retries", 1)

    async def handler(request):
        body = _json.loads(request.content)
        if body.get("device_id") == 4620:
            return httpx.Response(500, text="Server Error")
        return httpx.Response(200, json={"id": f"task-{body['device_id']}", "created_at": 1})

    respx.post("https://dev.leo4.ru/api/v1/device-tasks/").mock(side_effect=handler)

    result = await mass_activate(
        device_ids=[4619, 4620, 4621],
        method_code=20,
        payload={"dt": [{"mt": 0}]},
    )
    assert result["total"] == 3
    assert result["failed"] >= 1


@pytest.mark.asyncio
async def test_dry_run_open_cell(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", True)
    result = await open_cell_and_confirm(device_id=4619, cell_number=5)
    assert result["physical_confirmation"]["confirmed"] is True
