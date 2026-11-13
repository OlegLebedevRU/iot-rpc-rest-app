"""Authorized handover is distinct from concurrently active certificates."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from core.services import devices
from core.services import renewal_collision as arbiter
from core.services.renewal_collision import Decision, ROTATION_KEY, decide_handover

SN = "SYNTHETIC_ROTATION"
OLD = "2026-01-01T00:00:00Z - 2027-01-01T00:00:00Z"
NEW = "2026-02-01T00:00:00Z - 2027-02-01T00:00:00Z"
NEXT = "2026-03-01T00:00:00Z - 2027-03-01T00:00:00Z"
SUBJECT = f"CN={SN},O=1,OU=1234567"
NOW = datetime(2026, 4, 1, tzinfo=UTC)


def connection(validity=NEW, name="new"):
    return {
        "peer_cert_validity": validity,
        "peer_cert_subject": SUBJECT,
        "name": name,
        "conn_name": name,
        "user": SN,
        "ssl": True,
    }


def evaluate(**overrides):
    values = dict(
        sn=SN,
        device_id=1234567,
        previous=connection(OLD, "old"),
        candidate=connection(),
        connections=[connection()],
        task_id="task-1",
        now=NOW,
    )
    values.update(overrides)
    return decide_handover(**values)


def test_sequential_renewal_consumes_one_permit():
    decision, state = evaluate()
    assert decision is Decision.ALLOW
    assert state["current"] == NEW and state["retired"] == [OLD]
    previous = connection()
    previous[ROTATION_KEY] = state
    assert evaluate(previous=previous, task_id=None)[0] is Decision.ALLOW
    assert (
        evaluate(
            previous=previous,
            candidate=connection(NEXT),
            connections=[connection(NEXT)],
        )[0]
        is Decision.BLOCK
    )
    assert (
        evaluate(
            previous=previous,
            candidate=connection(NEXT),
            connections=[connection(NEXT)],
            task_id="task-2",
        )[0]
        is Decision.ALLOW
    )


@pytest.mark.parametrize("task_id", [None, "task-1"])
def test_old_certificate_never_returns(task_id):
    _, state = evaluate()
    previous = connection()
    previous[ROTATION_KEY] = state
    assert (
        evaluate(
            previous=previous,
            candidate=connection(OLD),
            connections=[connection(OLD)],
            task_id=task_id,
        )[0]
        is Decision.BLOCK
    )


def test_concurrent_certificates_block_even_during_renewal_same_nat():
    active = [
        dict(connection(), peer_host="192.0.2.1"),
        dict(connection(OLD, "old"), peer_host="192.0.2.1"),
    ]
    assert evaluate(connections=active)[0] is Decision.BLOCK


def test_task_creation_alone_does_not_authorize_rotation():
    assert evaluate(task_id=None)[0] is Decision.BLOCK


@pytest.mark.parametrize(
    "connections", [None, [], [connection(name="already_replaced")]]
)
def test_uncertain_broker_or_stale_event_is_deferred(connections):
    assert evaluate(connections=connections)[0] is Decision.DEFER


def test_foreign_identity_and_decreasing_validity_rejected():
    foreign = dict(connection(), peer_cert_subject=f"CN={SN},O=1,OU=7654321")
    assert evaluate(candidate=foreign, connections=[foreign])[0] is Decision.BLOCK
    foreign = dict(connection(), peer_cert_subject=f"CN={SN},O=2,OU=1234567")
    assert evaluate(candidate=foreign, connections=[foreign])[0] is Decision.BLOCK
    assert evaluate(previous=connection(NEXT, "old"))[0] is Decision.BLOCK


def test_metadata_is_not_a_fingerprint_or_unverified_statement():
    assert evaluate(connections=[dict(connection(), ssl=False)])[0] is Decision.DEFER
    assert (
        evaluate(connections=[dict(connection(), peer_cert_validity=NEXT)])[0]
        is Decision.DEFER
    )
    assert (
        evaluate(candidate=dict(connection(), peer_cert_subject=None))[0]
        is Decision.DEFER
    )
    assert arbiter.subject_identity(SUBJECT + ",CN=duplicate") is None
    assert arbiter.validity_period("2026-01-01 - 2027-01-01") is None


@pytest.mark.anyio
async def test_durable_arbitration_uses_locked_device_and_delivered_task(monkeypatch):
    row = SimpleNamespace(details=connection(OLD, "old"), is_blocked=False)

    def result(value):
        return MagicMock(scalar_one_or_none=MagicMock(return_value=value))

    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                result(SimpleNamespace(device_id=1234567)),
                result(row),
                result(None),
                result(uuid4()),
            ]
        ),
        add=MagicMock(),
    )
    broker = AsyncMock(return_value=[connection()])
    monkeypatch.setattr(arbiter.RmqAdminApi, "get_device_connections_strict", broker)
    candidate = connection()
    assert await arbiter.arbitrate_renewal(session, SN, candidate) is Decision.ALLOW
    assert ROTATION_KEY not in candidate
    assert session.add.call_args.args[0].var_key == "renewal.collision.1234567"
    statements = [str(call.args[0]) for call in session.execute.await_args_list]
    assert "FOR UPDATE" in statements[0]
    assert "locked_at" in statements[3] and "payload" not in statements[3]
    broker.assert_awaited_once_with(SN)


@pytest.mark.anyio
@pytest.mark.parametrize("decision", [Decision.ALLOW, Decision.BLOCK, Decision.DEFER])
async def test_event_handler_obeys_arbiter(monkeypatch, decision):
    monkeypatch.setattr(
        devices.RmqAdminApi,
        "get_single_connection_details",
        AsyncMock(return_value=connection()),
    )
    monkeypatch.setattr(
        devices,
        "evaluate_connection_collision",
        lambda **kw: ("SN_COLLISION", {"test": True}),
    )
    monkeypatch.setattr(devices, "arbitrate_renewal", AsyncMock(return_value=decision))
    block = AsyncMock()
    update = AsyncMock(return_value=True)
    monkeypatch.setattr(devices.DeviceRepo, "mark_device_blocked", block)
    monkeypatch.setattr(devices.DeviceRepo, "handle_connection_created", update)
    monkeypatch.setattr(devices.RmqAdminApi, "block_device_user", AsyncMock())
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    await devices.DeviceService.handle_connection_event(
        session, "connection.created", {"user": SN, "name": "new"}, {}
    )
    assert block.await_count == int(decision is Decision.BLOCK)
    assert update.await_count == int(decision is Decision.ALLOW)
    assert session.rollback.await_count == int(decision is Decision.DEFER)


@pytest.mark.anyio
async def test_persisted_generation_survives_stale_telemetry_and_restart(monkeypatch):
    import json

    _, state = evaluate()
    record = SimpleNamespace(var_val=json.dumps(state))
    row = SimpleNamespace(details=connection(OLD, "old"), is_blocked=False)

    def result(value):
        return MagicMock(scalar_one_or_none=MagicMock(return_value=value))

    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                result(SimpleNamespace(device_id=1234567)),
                result(row),
                result(record),
            ]
        ),
        add=MagicMock(),
    )
    monkeypatch.setattr(
        arbiter.RmqAdminApi,
        "get_device_connections_strict",
        AsyncMock(return_value=[connection()]),
    )
    assert await arbiter.arbitrate_renewal(session, SN, connection()) is Decision.ALLOW
    assert (
        session.execute.await_count == 3
    )  # No new task or process-local history needed.
    session.add.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status,body,expected",
    [
        (500, [], None),
        (200, [{"user": "foreign", "name": "n"}], None),
        (200, [connection()] * 17, None),
        (200, {}, None),
        (200, [], []),
        (200, [connection()], [connection()]),
    ],
)
async def test_strict_snapshot_never_treats_failure_as_empty(
    monkeypatch, status, body, expected
):
    response = SimpleNamespace(status_code=status, content=b"[]", json=lambda: body)
    client = SimpleNamespace(get=AsyncMock(return_value=response))
    manager = MagicMock(
        __aenter__=AsyncMock(return_value=client), __aexit__=AsyncMock()
    )
    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: manager)
    assert await arbiter.RmqAdminApi.get_device_connections_strict(SN) == expected


@pytest.mark.anyio
@pytest.mark.parametrize(
    "failure", [None, "closed", "wrong_name", "wrong_user", "oversized", "timeout"]
)
async def test_summary_snapshot_loads_tls_detail_for_each_socket(monkeypatch, failure):
    import httpx

    summary = {"user": SN, "name": "new"}
    detail = connection()
    if failure == "wrong_name":
        detail["name"] = "another"
    if failure == "wrong_user":
        detail["user"] = "another"

    async def get(path):
        if "/username/" in path:
            return SimpleNamespace(
                status_code=200, content=b"[]", json=lambda: [summary]
            )
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic")
        return SimpleNamespace(
            status_code=404 if failure == "closed" else 200,
            content=b"x" * (65537 if failure == "oversized" else 2),
            json=lambda: detail,
        )

    client = SimpleNamespace(get=AsyncMock(side_effect=get))
    manager = MagicMock(
        __aenter__=AsyncMock(return_value=client), __aexit__=AsyncMock()
    )
    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: manager)
    result = await arbiter.RmqAdminApi.get_device_connections_strict(SN)
    assert result == ([detail] if failure is None else None)
    assert client.get.await_count == 2


@pytest.mark.anyio
async def test_completed_recovery_requires_committed_result_and_window_bound_inventory():
    from sqlalchemy.dialects import postgresql

    task = uuid4()
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=task))
        )
    )
    assert await arbiter.completed_handover_task(session, 1234567, SN, NEW, NOW) == str(
        task
    )
    statement = session.execute.await_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    for required in [
        "tb_dev_events",
        "locked_at",
        "created_at",
        "org_id",
        "443",
        "324",
        "applied",
        "200",
        "7011",
    ]:
        assert required in sql
    assert "tb_dev_task_payload" not in sql and "pin" not in sql.lower()
    session.execute.return_value.scalar_one_or_none.return_value = None
    assert await arbiter.completed_handover_task(session, 1234567, SN, NEW, NOW) is None
    session.execute.reset_mock()
    assert (
        await arbiter.completed_handover_task(session, 1234567, SN, "bad", NOW) is None
    )
    session.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_deferred_handover_recovers_completed_task_without_new_execution(
    monkeypatch,
):
    row = SimpleNamespace(details=connection(OLD, "old"), is_blocked=False)
    task = uuid4()

    def result(value):
        return MagicMock(scalar_one_or_none=MagicMock(return_value=value))

    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                result(SimpleNamespace(device_id=1234567)),
                result(row),
                result(None),
                result(None),
                result(task),
            ]
        ),
        add=MagicMock(),
    )
    monkeypatch.setattr(
        arbiter.RmqAdminApi,
        "get_device_connections_strict",
        AsyncMock(return_value=[connection()]),
    )
    assert await arbiter.arbitrate_renewal(session, SN, connection()) is Decision.ALLOW
    import json

    assert json.loads(session.add.call_args.args[0].var_val)["task_id"] == str(task)


@pytest.mark.anyio
@pytest.mark.parametrize("decision", [Decision.ALLOW, Decision.BLOCK, Decision.DEFER])
async def test_reconciliation_uses_same_generation_arbitration(monkeypatch, decision):
    row = SimpleNamespace(
        client_id=SN,
        details=connection(OLD, "old"),
        is_blocked=False,
        last_checked_result=False,
        checked_at=None,
        connected_at=None,
    )
    monkeypatch.setattr(
        devices.DeviceRepo, "get_all_connections", AsyncMock(return_value=[row])
    )
    monkeypatch.setattr(
        devices.RmqAdminApi,
        "get_all_connections",
        AsyncMock(return_value=[connection()]),
    )
    arbitrate = AsyncMock(return_value=decision)
    monkeypatch.setattr(devices, "arbitrate_renewal", arbitrate)
    block = AsyncMock()
    monkeypatch.setattr(devices.DeviceRepo, "mark_device_blocked", block)
    monkeypatch.setattr(devices.RmqAdminApi, "block_device_user", AsyncMock())
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    stats = await devices.DeviceService.reconcile_device_connections(
        session, time_budget=10, chunk_size=10
    )
    arbitrate.assert_awaited_once()
    assert block.await_count == int(decision is Decision.BLOCK)
    assert stats["updated_telemetry"] == int(decision is Decision.ALLOW)
    assert row.last_checked_result == (decision is Decision.ALLOW)
