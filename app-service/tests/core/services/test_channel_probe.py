import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from core.services import channel_probe as probe


@pytest.fixture(autouse=True)
def reset_limits(monkeypatch):
    monkeypatch.setattr(probe, "_rates", {})
    monkeypatch.setattr(probe, "_global_rate", (0.0, 0))


def message(*, event=False, marker="1", **extra):
    request_nonce = str(uuid4())
    payload = {"v": 1, "type": "channel_probe", **extra}
    headers = {"iot_probe": marker}
    if event:
        payload["request_nonce"] = request_nonce
        headers.update(event_type_code="0", dev_event_id="123")
    return (
        SimpleNamespace(headers=headers, body=json.dumps(payload).encode()),
        request_nonce,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("event", [False, True])
async def test_probe_exact_wire_and_readonly_identity(monkeypatch, event):
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=77), commit=AsyncMock(), add=MagicMock()
    )
    publish = AsyncMock()
    monkeypatch.setattr(probe.topic_publisher, "publish", publish)
    msg, request_nonce = message(event=event)
    correlation = uuid4()
    assert await probe.dispatch_probe(msg, session, "a3b123", correlation, event=event)
    session.scalar.assert_awaited_once()
    session.commit.assert_not_awaited()
    session.add.assert_not_called()
    reply = publish.await_args.kwargs
    assert reply["routing_key"] == f"srv.a3b123.{'eva' if event else 'rsp'}"
    assert reply["correlation_id"] == str(correlation)
    assert reply["expiration"].total_seconds() == 10
    assert reply["headers"]["iot_probe"] == "1"
    assert reply["message"] == {
        "v": 1,
        "type": "channel_probe",
        "status": "success",
        **({"request_nonce": request_nonce} if event else {}),
    }
    assert reply["headers"] == {
        "iot_probe": "1",
        "correlationData": str(correlation),
        **(
            {"event_type_code": "0", "dev_event_id": "123"}
            if event
            else {"method_code": "0"}
        ),
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_marker",
        "extra",
        "zero",
        "bad_json",
        "oversize",
        "same_nonce",
        "zero_id",
        "wrong_code",
        "wrong_sn",
    ],
)
async def test_marked_invalid_never_falls_through(monkeypatch, mutation):
    msg, nonce = message(event=True)
    correlation = uuid4()
    sn = "a3b123"
    if mutation == "unknown_marker":
        msg.headers["iot_probe"] = "2"
    if mutation == "extra":
        msg.body = json.dumps(
            {"v": 1, "type": "channel_probe", "request_nonce": nonce, "dt": []}
        ).encode()
    if mutation == "zero":
        correlation = UUID(int=0)
    if mutation == "bad_json":
        msg.body = b"{"
    if mutation == "oversize":
        msg.body = b" " * 513
    if mutation == "same_nonce":
        correlation = UUID(nonce)
    if mutation == "zero_id":
        msg.headers["dev_event_id"] = "0"
    if mutation == "wrong_code":
        msg.headers["event_type_code"] = "76"
    if mutation == "wrong_sn":
        sn = "other/device"
    lookup, publish = AsyncMock(), AsyncMock()
    monkeypatch.setattr(probe, "_known_identity", lookup)
    monkeypatch.setattr(probe.topic_publisher, "publish", publish)
    assert await probe.dispatch_probe(msg, object(), sn, correlation, event=True)
    lookup.assert_not_awaited()
    publish.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "failure", [None, RuntimeError("DB unavailable"), TimeoutError()]
)
@pytest.mark.parametrize("event", [False, True])
async def test_unbound_or_unavailable_identity_fails_closed(
    monkeypatch, failure, event
):
    lookup = AsyncMock(return_value=False)
    if failure is not None:
        lookup.side_effect = failure
    monkeypatch.setattr(probe, "_known_identity", lookup)
    publish = AsyncMock()
    monkeypatch.setattr(probe.topic_publisher, "publish", publish)
    msg, nonce = message(event=event)
    correlation = uuid4()
    assert await probe.dispatch_probe(msg, object(), "a3b123", correlation, event=event)
    reply = publish.await_args.kwargs
    assert reply["correlation_id"] == str(correlation)
    assert reply["message"] == {
        "v": 1,
        "type": "channel_probe",
        "status": "error",
        **({"request_nonce": nonce} if event else {}),
    }


def test_bounded_rate_and_expiry(monkeypatch):
    # Ten sequential REQ+EVT barriers, plus bounded headroom for route hops.
    assert all(probe._allow("a3b123", 100) for _ in range(20))
    assert all(probe._allow("a3b123", 100) for _ in range(44))
    assert not probe._allow("a3b123", 100)
    assert probe._allow("a3b123", 110)
    monkeypatch.setattr(probe, "_rates", {str(i): (110, 1) for i in range(4096)})
    assert not probe._allow("new", 110)
    assert probe._allow("new", 120)
    monkeypatch.setattr(probe, "_global_rate", (120, 128))
    assert not probe._allow("new", 120)


@pytest.mark.anyio
async def test_lookup_timeout_leaves_bounded_error_reply(monkeypatch):
    async def slow_lookup(session, sn):
        await asyncio.sleep(1)
        return True

    monkeypatch.setattr(probe, "PROBE_IDENTITY_SECONDS", 0.01)
    monkeypatch.setattr(probe, "_known_identity", slow_lookup)
    publish = AsyncMock()
    monkeypatch.setattr(probe.topic_publisher, "publish", publish)
    msg, _ = message()
    assert await probe.dispatch_probe(msg, object(), "a3b123", uuid4(), event=False)
    assert publish.await_args.kwargs["message"]["status"] == "error"


@pytest.mark.anyio
async def test_expired_total_budget_never_publishes(monkeypatch):
    ticks = iter([100.0, 100.0, 111.0])
    monkeypatch.setattr(
        probe, "time", SimpleNamespace(monotonic=lambda: next(ticks, 111.0))
    )
    monkeypatch.setattr(probe, "_known_identity", AsyncMock(return_value=True))
    publish = AsyncMock()
    monkeypatch.setattr(probe.topic_publisher, "publish", publish)
    msg, _ = message()
    assert await probe.dispatch_probe(msg, object(), "a3b123", uuid4(), event=False)
    publish.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "body",
    [
        b'{"v":true,"type":"channel_probe"}',
        b'{"v":1.0,"type":"channel_probe"}',
        b'{"v":"1","type":"channel_probe"}',
        b'{"v":1,"v":1,"type":"channel_probe"}',
    ],
)
async def test_ambiguous_version_or_duplicate_fields_refused(monkeypatch, body):
    lookup = AsyncMock()
    monkeypatch.setattr(probe, "_known_identity", lookup)
    msg = SimpleNamespace(headers={"iot_probe": "1"}, body=body)
    assert await probe.dispatch_probe(msg, object(), "a3b123", uuid4(), event=False)
    lookup.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("event", [False, True])
async def test_topology_probe_bypasses_task_event_billing(monkeypatch, event):
    from core.topologys import fs_queues

    handler = AsyncMock(return_value=True)
    monkeypatch.setattr(fs_queues, "dispatch_probe", handler)
    billing, tasks, collector = AsyncMock(), MagicMock(), MagicMock()
    monkeypatch.setattr(fs_queues, "_publish_billing_for_sn", billing)
    monkeypatch.setattr(fs_queues, "DeviceTasksService", tasks)
    monkeypatch.setattr(fs_queues, "DeviceEventsCollect", collector)
    msg, _ = message(event=event)
    await (fs_queues.add_one_event if event else fs_queues.req)(
        msg, object(), "a3b123", uuid4()
    )
    billing.assert_not_awaited()
    tasks.assert_not_called()
    collector.assert_not_called()


@pytest.mark.anyio
async def test_polling_update_capability_does_not_consume_other_tasks(monkeypatch):
    from core.services import device_tasks

    service = device_tasks.DeviceTasksService(object(), 0)
    select_task = AsyncMock(return_value=None)
    monkeypatch.setattr(service, "_select_task", select_task)
    monkeypatch.setattr(device_tasks, "send_rsp", AsyncMock())
    methods = {7001, 7002, 7003, 7011, 7021, 7023, 7030, 7031, 7032, 7033}
    msg = SimpleNamespace(headers={"rpc_methods": ",".join(map(str, sorted(methods)))})
    await service.select("a3b123", UUID(int=0), msg)
    select_task.assert_awaited_once_with("a3b123", UUID(int=0), 7033, methods)
