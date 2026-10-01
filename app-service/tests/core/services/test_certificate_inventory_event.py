"""Event75 keeps the regular storage/webhook/EVA path and original inventory."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from core.services import device_events_collect as collector_module
from core.services.billing_utils import evt_billing_counter_type


def test_certificate_inventory_has_no_billing_counter():
    assert evt_billing_counter_type(75, [44]) is None
    assert evt_billing_counter_type(75, [75]) is None


@pytest.mark.anyio
@pytest.mark.parametrize("code", [75, 999, 44])
async def test_event_handler_skips_only_75_billing(monkeypatch, code):
    from core.topologys import fs_queues

    collector = MagicMock()
    collector.add = AsyncMock()
    publisher = AsyncMock()
    monkeypatch.setattr(
        fs_queues, "DeviceEventsCollect", MagicMock(return_value=collector)
    )
    monkeypatch.setattr(fs_queues, "_publish_billing_for_sn", publisher)
    message = SimpleNamespace(headers={"event_type_code": str(code)})
    session = object()
    await fs_queues.add_one_event(message, session, "event-test-device", None)
    collector.add.assert_awaited_once_with(message, corr_id=None)
    if code == 75:
        publisher.assert_not_awaited()
    else:
        publisher.assert_awaited_once_with(
            session, "event-test-device", "activity" if code == 44 else "evt"
        )


@pytest.mark.anyio
@pytest.mark.parametrize("handler", ["req", "result"])
async def test_rpc_requires_correlation_before_processing(monkeypatch, handler):
    from core.topologys import fs_queues

    tasks = MagicMock()
    publisher = AsyncMock()
    monkeypatch.setattr(fs_queues, "DeviceTasksService", tasks)
    monkeypatch.setattr(fs_queues, "_publish_billing_for_sn", publisher)
    await getattr(fs_queues, handler)(
        SimpleNamespace(body=b"{}"), object(), "test", None
    )
    tasks.assert_not_called()
    publisher.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("is_new", [True, False])
async def test_inventory_payload_and_duplicate_eva(monkeypatch, is_new):
    payload = {
        "101": 123,
        "102": "2026-10-01T12:00:00Z",
        "200": 75,
        "300": [
            {
                "324": "event-test-device",
                "440": "l4con",
                "441": "example-thumbprint",
                "442": "example-serial",
                "443": "2030-01-01T00:00:00Z",
                "444": [{"name": "l4con", "path": "l4con/l4con.exe", "present": True}],
                "445": None,
            }
        ],
    }
    correlation = uuid4()
    payload["correlationData"] = str(correlation)
    message = SimpleNamespace(
        headers={
            "event_type_code": "75",
            "dev_event_id": "123",
            "dev_timestamp": "2026-10-01T12:00:00Z",
        },
        body=json.dumps(payload).encode(),
    )
    lookup = AsyncMock(return_value=70001)
    save = AsyncMock(return_value=is_new)
    webhook = AsyncMock()
    eva = AsyncMock()
    monkeypatch.setattr(collector_module.DeviceRepo, "get_device_id", lookup)
    monkeypatch.setattr(collector_module.EventRepository, "add_event", save)
    monkeypatch.setattr(collector_module.topic_publisher, "publish", webhook)
    monkeypatch.setattr(collector_module, "send_eva", eva)
    session = object()
    await collector_module.DeviceEventsCollect(session, "event-test-device").add(
        message, corr_id=correlation
    )
    lookup.assert_awaited_once_with(session=session, sn="event-test-device")
    event = save.await_args.args[1]
    assert event.device_id == 70001 and event.event_type_code == 75
    assert event.dev_event_id == 123 and event.payload == payload
    assert event.dev_timestamp == 1790856000
    assert webhook.await_count == int(is_new)
    eva.assert_awaited_once_with(
        sn="event-test-device",
        event_type_code=75,
        dev_event_id=123,
        corr_id=correlation,
        status="success",
    )
