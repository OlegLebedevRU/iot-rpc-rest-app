"""PB identity-transfer contract: owner guard, teardown ordering and exact replay."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from core.models.devices import Device, DeviceOrgBind, DeviceTag, Org
from core.services import identity_transfer as service


@pytest.fixture
def context(monkeypatch):
    request = service.IdentityTransferRequest(
        operation_id=uuid4(),
        terminal_id=101,
        device_id=4625,
        sn="fixture-sn",
        source_org_id=1,
        target_org_id=2,
    )
    device = Device(device_id=4625, sn=request.sn, is_deleted=False)
    binding = DeviceOrgBind(device_id=4625, org_id=1)
    db = AsyncMock()
    db.add = MagicMock()
    query_result = MagicMock()
    query_result.one_or_none.return_value = (device, binding)
    query_result.scalars.return_value.all.return_value = []
    db.execute.return_value = query_result
    db.scalar.side_effect = [Org(org_id=2, is_deleted=False), None]
    provisions = MagicMock()
    provisions.all.return_value = []
    sessions = MagicMock()
    sessions.all.return_value = []
    db.scalars.side_effect = [provisions, sessions]
    leases = SimpleNamespace(
        get_active_by_sn=AsyncMock(return_value=None), revoke=AsyncMock()
    )
    monkeypatch.setattr(service, "lease_registry", leases)
    audit = AsyncMock()
    monkeypatch.setattr(service.DeviceRepo, "add_audit_log", audit)
    return request, device, binding, db, leases, audit


@pytest.mark.anyio
async def test_transfer_closes_old_access_before_changing_owner_and_preserves_security(
    context, monkeypatch
):
    request, device, binding, db, leases, audit = context
    leases.get_active_by_sn.return_value = SimpleNamespace(lease_id=uuid4())
    leases.revoke.return_value = leases.get_active_by_sn.return_value
    active = SimpleNamespace(session_id="fixture-console", tenant_id=1)
    provisions = MagicMock()
    provisions.all.return_value = []
    sessions = MagicMock()
    sessions.all.return_value = [active]
    db.scalars.side_effect = [provisions, sessions]

    async def stop(session, session_id, data):
        assert binding.org_id == 1
        assert data.tenant_id == 1 and data.reason == "identity_transfer"

    stopper = AsyncMock(side_effect=stop)
    monkeypatch.setattr(service.remote_session_event_service, "stop_session", stopper)
    result = await service.transfer_identity(db, request)
    assert result["org_id"] == 2 and binding.org_id == 2
    assert device.sn == request.sn and device.device_id == 4625
    leases.revoke.assert_awaited_once()
    stopper.assert_awaited_once()
    db.commit.assert_awaited_once()
    assert "FOR UPDATE" in str(db.execute.call_args_list[0].args[0])
    assert any(isinstance(call.args[0], DeviceTag) for call in db.add.call_args_list)
    assert not any(
        "tb_device_connections" in str(call.args[0])
        for call in db.execute.call_args_list
    )
    audit.assert_awaited_once()


@pytest.mark.anyio
async def test_wrong_source_is_rejected_without_mutation(context):
    request, _, binding, db, leases, _ = context
    binding.org_id = 3
    with pytest.raises(HTTPException) as exc:
        await service.transfer_identity(db, request)
    assert exc.value.status_code == 409 and binding.org_id == 3
    db.commit.assert_not_awaited()
    leases.revoke.assert_not_awaited()


@pytest.mark.anyio
async def test_same_operation_replays_but_different_payload_cannot_claim_target(
    context,
):
    request, _, binding, db, leases, _ = context
    binding.org_id = 2
    digest = hashlib.sha256(
        json.dumps(
            request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    db.scalar.side_effect = [Org(org_id=2, is_deleted=False), DeviceTag(value=digest)]
    result = await service.transfer_identity(db, request)
    assert result["operation_id"] == str(request.operation_id)
    leases.revoke.assert_not_awaited()
    db.scalar.side_effect = [
        Org(org_id=2, is_deleted=False),
        DeviceTag(value="different-operation"),
    ]
    with pytest.raises(HTTPException) as exc:
        await service.transfer_identity(db, request)
    assert exc.value.status_code == 409


@pytest.mark.anyio
async def test_teardown_failure_never_changes_org(context, monkeypatch):
    request, _, binding, db, _, _ = context
    provisions = MagicMock()
    provisions.all.return_value = []
    sessions = MagicMock()
    sessions.all.return_value = [
        SimpleNamespace(session_id="fixture-console", tenant_id=1)
    ]
    db.scalars.side_effect = [provisions, sessions]
    monkeypatch.setattr(
        service.remote_session_event_service,
        "stop_session",
        AsyncMock(side_effect=RuntimeError("fixture teardown failure")),
    )
    with pytest.raises(RuntimeError):
        await service.transfer_identity(db, request)
    assert binding.org_id == 1
    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_control_lookup_locks_actual_owner_binding():
    from sqlalchemy.dialects.postgresql import dialect

    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    assert (
        await service.DeviceRepo.get_device_id(
            db, sn="fixture-sn", org_id=1, lock_binding=True
        )
        is None
    )
    statement = db.execute.call_args.args[0]
    sql = str(statement.compile(dialect=dialect()))
    assert "FOR UPDATE OF tb_device_org_binds" in sql
    assert 1 in statement.compile().params.values()
    assert "tb_device_org_binds.org_id" in sql
