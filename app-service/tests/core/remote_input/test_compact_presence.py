from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from core.remote_input.mqtt_bridge import handle_device_ctl_message
from core.remote_input.presence import RedisPresenceRegistry
from core.remote_input.schemas import CtlPresence, InventoryInfo, ScreenInfo


@pytest.mark.asyncio
async def test_compact_presence_lifecycle(monkeypatch):
    store = RedisPresenceRegistry()
    sn = "test-compact-ctl"
    topic = f"dev.{sn}.ctl"
    revision = "2d438fe300000001"
    key = f"l4d:presence:{sn}"
    send = AsyncMock()
    monkeypatch.setattr("core.remote_input.publisher.send_ctl_command", send)
    beat = {"v": 1, "type": "heartbeat", "presence_rev": revision, "seq": 1}

    async def receive(payload):
        return await handle_device_ctl_message(
            routing_key=topic, payload=payload, p_registry=store
        )

    assert await receive(beat)
    assert await receive(beat)
    assert send.await_count == 1
    assert not (await store.get(sn)).online

    full = CtlPresence(
        timestamp=datetime.now(UTC).isoformat(),
        presence_rev=revision,
        inventory=InventoryInfo(),
        desktop_available=True,
        screen=ScreenInfo(
            virtual_x=0, virtual_y=0, virtual_width=800, virtual_height=600
        ),
    )
    await store.update(sn, full)
    before = await store._client.hget(key, "data")
    assert await receive(beat)
    touched = await store._client.hget(key, "received_at")
    assert await receive(beat)
    assert touched == await store._client.hget(key, "received_at")
    assert before == await store._client.hget(key, "data")
    assert (await store.get(sn)).online
    await store._client.delete(f"l4d:inventory:{sn}")
    assert await store.get_inventory(sn) == full.inventory

    await store.update(
        sn, CtlPresence(status="offline", timestamp=datetime.now(UTC).isoformat())
    )
    assert await receive({**beat, "seq": 2})
    assert not (await store.get(sn)).online
