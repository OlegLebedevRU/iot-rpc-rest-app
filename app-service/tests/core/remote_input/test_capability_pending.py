"""Concurrent inventory/START must await the same correlated agent reply."""

import asyncio
import copy
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from core.remote_input import video_models as wire
from core.remote_input.video_control import now_ms, video_control

from . import test_video_v2 as fixtures

env = fixtures.env
native_env = fixtures.native_env
fixture = fixtures.fixture


async def pending_for(native_env):
    service, lease, _, cap = native_env
    query = wire.InventoryGet(
        v=2,
        type="inventory_get",
        command_id=str(uuid4()),
        sn=lease.sn,
        issued_at_ms=now_ms(),
        expires_at_ms=now_ms() + 35000,
        source_id=cap["source_id"],
        profile_id="low",
    )

    def reserve(doc):
        doc.pop("capability", None)
        doc["pending"] = query.model_dump(mode="json")

    await video_control.store.change(lease.sn, reserve)
    return service, lease, copy.deepcopy(cap), query


@pytest.mark.anyio
async def test_same_display_waits_for_correlated_ready_without_second_publish(
    native_env,
):
    service, lease, cap, query = await pending_for(native_env)
    sender = AsyncMock()
    task = asyncio.create_task(
        video_control.capability(
            lease.sn,
            service.presence,
            sender,
            source_id=cap["source_id"],
            profile_id="low",
            contract_version=3,
        )
    )
    try:
        await asyncio.sleep(0.02)
        assert not task.done(), "Pending measurement is not an unsupported agent"
        cap.update(checked_at_ms=now_ms(), valid_until_ms=now_ms() + 59000)
        ack = fixture("capabilities")
        ack.update(command_id=str(uuid4()), video_capabilities=cap)
        assert not await video_control.accept_capability(
            lease.sn, wire.CapabilitiesAck.model_validate(ack)
        )
        assert not task.done()
        ack["command_id"] = query.command_id
        assert await video_control.accept_capability(
            lease.sn, wire.CapabilitiesAck.model_validate(ack)
        )
        result = await asyncio.wait_for(task, 1)
        assert result["negotiated_v2"] and result["video_capabilities"] == cap
        sender.assert_not_called()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.anyio
async def test_cancelled_joiner_does_not_clear_query_owned_by_other_request(native_env):
    service, lease, cap, query = await pending_for(native_env)
    sender = AsyncMock()
    task = asyncio.create_task(
        video_control.capability(
            lease.sn,
            service.presence,
            sender,
            source_id=cap["source_id"],
            profile_id="low",
            contract_version=3,
        )
    )
    await asyncio.sleep(0.02)
    task.cancel()
    result = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError)
    doc = await video_control.store.get(lease.sn)
    assert doc["pending"]["command_id"] == query.command_id
    sender.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize("difference", ["source", "profile", "expiry", "invalidation"])
async def test_pending_wait_keeps_source_deadline_and_invalidation_guards(
    native_env, monkeypatch, difference
):
    import core.remote_input.video_control as control

    service, lease, cap, query = await pending_for(native_env)
    sender = AsyncMock()
    task = asyncio.create_task(
        video_control.capability(
            lease.sn,
            service.presence,
            sender,
            source_id="another-display" if difference == "source" else cap["source_id"],
            profile_id="default" if difference == "profile" else "low",
            contract_version=3,
        )
    )
    try:
        await asyncio.sleep(0.02)
        if difference in ("expiry", "invalidation"):
            assert not task.done()
            if difference == "expiry":
                monkeypatch.setattr(control, "now_ms", lambda: query.expires_at_ms)
            else:
                await video_control.invalidate(lease.sn)
        result = await asyncio.wait_for(task, 1)
        assert not result["negotiated_v2"] and result["video_capabilities"] is None
        sender.assert_not_called()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
