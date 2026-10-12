from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from core.services import terminal_inventory_delivery as worker
from sqlalchemy.dialects import postgresql


@pytest.mark.anyio
async def test_batch_status_reports_broker_block_from_connection_model():
    from core.crud.device_repo import DeviceRepo

    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                fetchall=lambda: [(7, "fixture", True, 4, "fixture", True, None, None)]
            )
        )
    )
    statuses = await DeviceRepo.get_terminals_status_by_device_ids(session, [7, 8])
    assert statuses[0]["is_blocked"] and statuses[0]["is_online"]
    assert not statuses[1]["is_provisioned"]
    sql = str(session.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "tb_device_connections.is_blocked" in sql


@pytest.mark.anyio
@pytest.mark.parametrize("code", [13, 44, 74, 76, 999])
async def test_only_event75_can_enter_private_delivery(code):
    session = SimpleNamespace(execute=AsyncMock())
    await worker.enqueue_inventory(
        session, device_id=7, payload={"200": code}, correlation_data=uuid4()
    )
    session.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_queue_tenant_and_sn_come_from_binding_not_device_payload():
    owner = SimpleNamespace(org_id=4, sn="fixture")
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(one_or_none=lambda: owner))
    )
    event_uuid = uuid4()
    payload = {"200": 75, "300": [{"324": "foreign", "445": "1.13.43", "440": "l4con"}]}
    await worker.enqueue_inventory(
        session, device_id=7, payload=payload, correlation_data=event_uuid
    )
    assert session.execute.await_count == 1
    payload["300"][0]["324"] = "fixture"
    await worker.enqueue_inventory(
        session, device_id=7, payload=payload, correlation_data=event_uuid
    )
    statement = session.execute.await_args.args[0]
    params = statement.compile().params
    assert params["tenant_id"] == 4 and params["sn"] == "fixture"
    assert params["event"]["correlationData"] == str(event_uuid)
    assert "ON CONFLICT (event_uuid) DO NOTHING" in str(
        statement.compile(dialect=postgresql.dialect())
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "code,quarantine",
    [
        (200, False),
        (400, True),
        (409, True),
        (422, True),
        (404, False),
        (429, False),
        (503, False),
    ],
)
async def test_http_delivery_has_own_retry_state_and_never_calls_public_webhook(
    monkeypatch, code, quarantine
):
    now = datetime.now(UTC)
    delivery = SimpleNamespace(
        id=20,
        device_id=7,
        tenant_id=4,
        sn="fixture",
        event={"200": 75},
        attempts=0,
        next_attempt_at=now,
        created_at=now,
        finished_at=None,
        last_error=None,
    )
    owner = SimpleNamespace(org_id=4, sn="fixture")
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(one_or_none=lambda: (delivery, now)),
                SimpleNamespace(one_or_none=lambda: owner),
            ]
        )
    )
    context = AsyncMock()
    client = AsyncMock()
    context.__aenter__.return_value = client
    client.post.return_value = httpx.Response(
        code, request=httpx.Request("POST", "http://localhost/fixture")
    )
    monkeypatch.setattr(worker.httpx, "AsyncClient", lambda **kwargs: context)
    assert await worker.deliver_one(session)
    assert delivery.attempts == 1
    assert (delivery.finished_at is not None) == (code == 200 or quarantine)
    if code >= 400 and not quarantine:
        assert delivery.next_attempt_at > now
    sent = client.post.await_args.kwargs["json"]
    assert sent["source_revision"] == 20 and sent["tenant_id"] == 4
    sql = str(
        session.execute.await_args_list[0].args[0].compile(dialect=postgresql.dialect())
    )
    assert "FOR UPDATE OF tb_terminal_inventory_deliveries SKIP LOCKED" in sql


@pytest.mark.anyio
async def test_queued_old_tenant_is_discarded_after_rebind(monkeypatch):
    now = datetime.now(UTC)
    delivery = SimpleNamespace(
        device_id=7, tenant_id=4, sn="fixture", attempts=0, finished_at=None
    )
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(one_or_none=lambda: (delivery, now)),
                SimpleNamespace(
                    one_or_none=lambda: SimpleNamespace(org_id=5, sn="fixture")
                ),
            ]
        )
    )
    client = AsyncMock()
    monkeypatch.setattr(worker.httpx, "AsyncClient", client)
    assert await worker.deliver_one(session)
    assert delivery.last_error == "identity_changed"
    assert delivery.attempts == 0
    client.assert_not_called()


@pytest.mark.anyio
async def test_legacy_event_number_collision_still_enqueues_full_inventory_uuid(
    monkeypatch,
):
    from core.crud.dev_events_repo import EventRepository
    from core.schemas.device_events import DevEventBody
    from sqlalchemy.exc import IntegrityError

    enqueue = AsyncMock()
    monkeypatch.setattr(worker, "enqueue_inventory", enqueue)
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=4),
        add=lambda item: None,
        commit=AsyncMock(
            side_effect=[
                IntegrityError("fixture", {}, Exception("uq_dev_event_idempotent")),
                None,
            ]
        ),
        rollback=AsyncMock(),
    )
    correlation = uuid4()
    event = DevEventBody(
        device_id=7,
        event_type_code=75,
        dev_event_id=12,
        dev_timestamp=1,
        payload={"200": 75},
    )
    assert not await EventRepository.add_event(
        session, event, correlation_data=correlation
    )
    assert enqueue.await_count == 2
    assert enqueue.await_args.kwargs["correlation_data"] == correlation
    session.rollback.assert_awaited_once()
    assert session.commit.await_count == 2
