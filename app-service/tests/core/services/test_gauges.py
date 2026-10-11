"""Gauge queries distinguish absent snapshots from storage failures."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from core.services import devices


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("result", [None, SimpleNamespace(items=[])])
async def test_absent_gauge_is_404(monkeypatch, result):
    monkeypatch.setattr(
        devices.DeviceRepo, "get_gauges_page", AsyncMock(return_value=result)
    )
    with pytest.raises(HTTPException) as error:
        await devices.DeviceService.get_gauges(None, 1, device_id=4619, type="84")
    assert error.value.status_code == 404
    assert error.value.detail == "No gauges found"


@pytest.mark.anyio
async def test_storage_failure_remains_500(monkeypatch):
    monkeypatch.setattr(
        devices.DeviceRepo,
        "get_gauges_page",
        AsyncMock(side_effect=RuntimeError("storage unavailable")),
    )
    with pytest.raises(HTTPException) as error:
        await devices.DeviceService.get_gauges(None, 1, device_id=4619, type="84")
    assert error.value.status_code == 500
    assert error.value.detail == "Internal server error"


@pytest.mark.anyio
async def test_existing_gauge_is_returned(monkeypatch):
    result = SimpleNamespace(items=[{"type": "84"}])
    repository = AsyncMock(return_value=result)
    monkeypatch.setattr(devices.DeviceRepo, "get_gauges_page", repository)
    assert (
        await devices.DeviceService.get_gauges(None, 1, device_id=4619, type="84")
        is result
    )
    repository.assert_awaited_once_with(None, org_id=1, device_id=4619, type="84")
