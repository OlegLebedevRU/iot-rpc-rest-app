"""Tests for task tools."""
from __future__ import annotations
import pytest
import respx
import httpx

from leo4_mcp.config import settings
from leo4_mcp.tools.tasks import create_device_task, get_task_status, list_device_tasks


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "allowed_device_ids", [])
    # Reset singleton client
    import leo4_mcp.client as c_mod
    c_mod._client = None


@respx.mock
@pytest.mark.asyncio
async def test_create_device_task_success():
    respx.post("https://dev.leo4.ru/api/v1/device-tasks/").mock(
        return_value=httpx.Response(
            200, json={"id": "task-uuid-1", "created_at": 1712345678}
        )
    )
    result = await create_device_task(
        device_id=4619,
        method_code=51,
        payload={"dt": [{"cl": 5}]},
        ttl=5,
        priority=1,
        ext_task_id="test-001",
    )
    assert result["id"] == "task-uuid-1"


@respx.mock
@pytest.mark.asyncio
async def test_create_device_task_builds_correct_body():
    captured = {}

    async def handler(request):
        import json
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "x", "created_at": 1})

    respx.post("https://dev.leo4.ru/api/v1/device-tasks/").mock(side_effect=handler)
    await create_device_task(
        device_id=4620,
        method_code=20,
        payload={"dt": [{"mt": 0}]},
        ttl=3,
        priority=2,
        ext_task_id="my-ext-id",
    )
    body = captured["body"]
    assert body["device_id"] == 4620
    assert body["method_code"] == 20
    assert body["ttl"] == 3
    assert body["priority"] == 2
    assert body["ext_task_id"] == "my-ext-id"
    assert body["payload"] == {"dt": [{"mt": 0}]}


@respx.mock
@pytest.mark.asyncio
async def test_get_task_status():
    respx.get("https://dev.leo4.ru/api/v1/device-tasks/abc-123").mock(
        return_value=httpx.Response(
            200, json={"id": "abc-123", "status": 3, "status_name": "DONE"}
        )
    )
    result = await get_task_status("abc-123")
    assert result["status"] == 3
    assert result["status_name"] == "DONE"


@respx.mock
@pytest.mark.asyncio
async def test_list_device_tasks():
    respx.get("https://dev.leo4.ru/api/v1/device-tasks/").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [{"id": "t1", "status": 3}],
                "total": 1,
                "page": 1,
                "size": 1,
                "pages": 1,
            },
        )
    )
    result = await list_device_tasks(device_id=4619)
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_allowlist_blocks_device(monkeypatch):
    monkeypatch.setattr(settings, "allowed_device_ids", [4619])
    with pytest.raises(ValueError, match="not in LEO4_ALLOWED_DEVICE_IDS"):
        await create_device_task(device_id=9999, method_code=20)


@pytest.mark.asyncio
async def test_dry_run_create(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", True)
    result = await create_device_task(device_id=4619, method_code=20)
    assert result["status"] == 3
    assert result["device_id"] == 4619
