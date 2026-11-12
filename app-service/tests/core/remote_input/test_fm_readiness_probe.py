"""Readiness commands have a bounded TTL and never acquire a lease."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from core import file_manager_navigation as fm
from fastapi import HTTPException


@pytest.mark.anyio
async def test_probe_uses_existing_fmc_and_no_lease(monkeypatch):
    publish = AsyncMock()
    monkeypatch.setattr(fm.topic_publisher, "publish", publish)
    reserve = AsyncMock()
    monkeypatch.setattr(fm.lease_registry, "acquire", reserve)
    body = fm.ReadinessProbe(
        request_id=uuid4(), expires_at=datetime.now(UTC) + timedelta(seconds=7)
    )
    await fm.dispatch_probe("fixture", body)
    message = publish.call_args.kwargs["message"]
    assert message == {
        "v": 2,
        "action": "probe",
        "command_id": str(body.request_id),
        "expires_at": int(body.expires_at.timestamp()),
    }
    assert publish.call_args.kwargs["routing_key"].endswith(".fixture.fmc")
    assert publish.call_args.kwargs["persist"] is False
    reserve.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("seconds", [-1, 11])
async def test_invalid_deadline_is_rejected_without_publish(monkeypatch, seconds):
    publish = AsyncMock()
    monkeypatch.setattr(fm.topic_publisher, "publish", publish)
    body = fm.ReadinessProbe(
        request_id=uuid4(), expires_at=datetime.now(UTC) + timedelta(seconds=seconds)
    )
    with pytest.raises(HTTPException):
        await fm.dispatch_probe("fixture", body)
    publish.assert_not_awaited()
