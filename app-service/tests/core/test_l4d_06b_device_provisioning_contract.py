from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from httpx import ASGITransport, AsyncClient

from api.internal_v1.device_provisioning import router as device_provisioning_router
from core.config import settings
from core.models import db_helper
from core.models.device_provisioning import DeviceProvisioning
from core.models.devices import Device, DeviceAuditLog, DeviceConnection, DeviceOrgBind, Org
from core.models.remote_sessions import RemoteSession, RemoteSessionEvent
from core.schemas.device_provisioning import (
    DeviceProvisionRequest,
    DeviceProvisionResponse,
    DeviceProvisionStatus,
)
from core.schemas.remote_sessions import RemoteSessionEventType, validate_no_commercial_fields
from core.services.device_provisioning_service import (
    DeviceProvisioningService,
)
from main import main_app


class InMemoryAsyncSession:
    """Mock AsyncSession with in-memory persistence for provisioning, devices, and events."""

    def __init__(self) -> None:
        self.provisionings: dict[str, DeviceProvisioning] = {}  # operation_id -> record
        self.devices: dict[str, Device] = {}  # sn -> Device
        self.orgs: dict[int, Org] = {}  # org_id -> Org
        self.binds: dict[int, DeviceOrgBind] = {}  # device_id -> DeviceOrgBind
        self.connections: dict[int, DeviceConnection] = {}  # device_id -> DeviceConnection
        self.audit_logs: list[DeviceAuditLog] = []
        self.events: list[RemoteSessionEvent] = []
        self.sessions: dict[str, RemoteSession] = {}
        self._next_prov_id = 1
        self._next_cursor = 1
        self.is_mock = True

    def add(self, obj: Any) -> None:
        now = datetime.now(timezone.utc)
        if isinstance(obj, DeviceProvisioning):
            if obj.id is None:
                obj.id = self._next_prov_id
                self._next_prov_id += 1
            if getattr(obj, "created_at", None) is None:
                obj.created_at = now
            if getattr(obj, "updated_at", None) is None:
                obj.updated_at = now
            self.provisionings[obj.operation_id] = obj
        elif isinstance(obj, Device):
            self.devices[obj.sn] = obj
        elif isinstance(obj, Org):
            self.orgs[obj.org_id] = obj
        elif isinstance(obj, DeviceOrgBind):
            self.binds[obj.device_id] = obj
        elif isinstance(obj, DeviceConnection):
            self.connections[obj.device_id] = obj
        elif isinstance(obj, DeviceAuditLog):
            self.audit_logs.append(obj)
        elif isinstance(obj, RemoteSessionEvent):
            if obj.cursor is None:
                obj.cursor = self._next_cursor
                self._next_cursor += 1
            if getattr(obj, "created_at", None) is None:
                obj.created_at = now
            self.events.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def refresh(self, obj: Any) -> None:
        pass

    async def scalar(self, stmt: Any) -> Any:
        stmt_str = str(stmt).lower()

        # 1. max(Device.device_id) or max(DeviceProvisioning.device_id)
        if "max" in stmt_str:
            if "tb_device_provisionings" in stmt_str or "deviceprovisioning" in stmt_str:
                return max((p.device_id for p in self.provisionings.values()), default=0)
            if "tb_devices" in stmt_str or "device" in stmt_str:
                return max((d.device_id for d in self.devices.values()), default=0)

        # 2. Extract where criteria params
        where_criteria = getattr(stmt, "_where_criteria", ())
        params: dict[str, Any] = {}
        for c in where_criteria:
            if hasattr(c, "left") and hasattr(c, "right"):
                col = getattr(c.left, "key", None) or getattr(c.left, "name", None)
                val = getattr(c.right, "value", None)
                if col and val is not None:
                    params[col] = val

        try:
            compiled_params = stmt.compile().params
            for k, v in compiled_params.items():
                if isinstance(v, (str, int)):
                    for field in ("operation_id", "sn", "tenant_id", "terminal_id", "device_id", "org_id"):
                        if field in k.lower():
                            params[field] = v
        except Exception:
            pass

        # 3. tb_device_provisionings
        if "tb_device_provisionings" in stmt_str or "deviceprovisioning" in stmt_str:
            op_id = params.get("operation_id")
            if op_id and op_id in self.provisionings:
                return self.provisionings[op_id]

            sn = params.get("sn")
            tenant_id = params.get("tenant_id")
            terminal_id = params.get("terminal_id")
            dev_id = params.get("device_id")

            for p in reversed(list(self.provisionings.values())):
                match = True
                if op_id and p.operation_id != op_id:
                    match = False
                if sn and p.sn != sn:
                    match = False
                if tenant_id is not None and p.tenant_id != tenant_id:
                    match = False
                if terminal_id is not None and p.terminal_id != terminal_id:
                    match = False
                if dev_id is not None and p.device_id != dev_id:
                    match = False
                if match:
                    return p
            return None

        # 4. tb_devices
        if "tb_devices" in stmt_str or "device" in stmt_str:
            sn = params.get("sn")
            if sn and sn in self.devices:
                return self.devices[sn]
            dev_id = params.get("device_id")
            if dev_id is not None:
                for d in self.devices.values():
                    if d.device_id == dev_id:
                        return d
            return None

        # 5. tb_orgs
        if "tb_orgs" in stmt_str or "org" in stmt_str:
            org_id = params.get("org_id")
            if org_id is not None and org_id in self.orgs:
                return self.orgs[org_id]
            return None

        # 6. tb_device_org_binds
        if "tb_device_org_binds" in stmt_str:
            dev_id = params.get("device_id")
            if dev_id is not None and dev_id in self.binds:
                return self.binds[dev_id]
            return None

        # 7. tb_device_connections
        if "tb_device_connections" in stmt_str:
            dev_id = params.get("device_id")
            if dev_id is not None and dev_id in self.connections:
                return self.connections[dev_id]
            return None

        # 8. tb_remote_session_events
        if "tb_remote_session_events" in stmt_str or "event" in stmt_str:
            ev_id = params.get("event_id")
            op_id = params.get("operation_id")
            for ev in self.events:
                if ev_id and ev.event_id == ev_id:
                    return ev
                if op_id and ev.operation_id == op_id:
                    return ev
            return None

        return None

    async def scalars(self, stmt: Any) -> Any:
        class Result:
            def __init__(self, items: list[Any]) -> None:
                self._items = items

            def all(self) -> list[Any]:
                return self._items

        stmt_str = str(stmt).lower()
        if "tb_remote_session_events" in stmt_str:
            return Result(self.events)
        return Result([])

    async def execute(self, stmt: Any) -> Any:
        class ExecResult:
            def __init__(self, rows: list[Any]) -> None:
                self._rows = rows

            def first(self) -> Any:
                return self._rows[0] if self._rows else None

            def all(self) -> list[Any]:
                return self._rows

        stmt_str = str(stmt).lower()

        # Handle join between Device and DeviceOrgBind
        if "from tb_devices" in stmt_str or "from tb_device" in stmt_str:
            where_criteria = getattr(stmt, "_where_criteria", ())
            target_sn = None
            for c in where_criteria:
                if hasattr(c, "left") and hasattr(c, "right"):
                    col = getattr(c.left, "key", None) or getattr(c.left, "name", None)
                    if col == "sn":
                        target_sn = getattr(c.right, "value", None)
            if target_sn and target_sn in self.devices:
                dev = self.devices[target_sn]
                bind = self.binds.get(dev.device_id)
                org_id = bind.org_id if bind else None
                return ExecResult([(dev, org_id)])
            return ExecResult([])

        # Handle aggregate queries on events
        if "count" in stmt_str and "min" in stmt_str:
            count = len(self.events)
            min_c = min((e.cursor for e in self.events), default=None)
            max_c = max((e.cursor for e in self.events), default=None)
            return ExecResult([(count, min_c, max_c)])

        if "group by tb_remote_session_events.event_type" in stmt_str or "group_by" in stmt_str:
            counts: dict[str, int] = {}
            for ev in self.events:
                counts[ev.event_type] = counts.get(ev.event_type, 0) + 1
            return ExecResult(list(counts.items()))

        return ExecResult([])


# ── Fixtures ────────────────────────────────────────────────────────────────────


@pytest.fixture
def in_memory_session() -> InMemoryAsyncSession:
    return InMemoryAsyncSession()


@pytest.fixture
def app_with_in_memory_db(in_memory_session: InMemoryAsyncSession):
    async def fake_session_getter():
        yield in_memory_session

    main_app.dependency_overrides[db_helper.session_getter] = fake_session_getter
    yield main_app, in_memory_session
    main_app.dependency_overrides.clear()


# ── Test Cases ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_duplicate_request_idempotency_flow(app_with_in_memory_db, monkeypatch):
    """Initial provisioning returns 201 Created (replayed_flag=False).

    Exact duplicate request returns 200 OK (replayed_flag=True) with identical attributes.
    """
    app, session = app_with_in_memory_db
    monkeypatch.setattr(settings.auth, "internal_service_key", "sec-prov-key")

    headers = {"X-Internal-Service-Key": "sec-prov-key"}
    req_payload = {
        "operation_id": "018f3a5b-0006-7001-8000-000000000001",
        "contract_version": "1.0.0",
        "tenant_id": 10,
        "terminal_id": 101,
        "sn": "SN-IDEM-001",
        "device_id": None,
        "correlation_id": "corr-idem-1",
        "requested_by_user_id": "user-1",
        "metadata": {"zone": "east", "model": "edge-v1"},
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. First call: new provisioning -> 201 Created
        resp1 = await ac.post("/api/internal/v1/devices/provision", json=req_payload, headers=headers)
        assert resp1.status_code == 201
        data1 = resp1.json()
        assert data1["operation_id"] == req_payload["operation_id"]
        assert data1["status"] == "provisioned"
        assert data1["replayed_flag"] is False
        assert data1["tenant_id"] == 10
        assert data1["terminal_id"] == 101
        assert data1["sn"] == "SN-IDEM-001"
        assert data1["device_id"] >= 1000
        first_device_id = data1["device_id"]

        # 2. Second call: exact same payload and operation_id -> 200 OK (replayed_flag=True)
        resp2 = await ac.post("/api/internal/v1/devices/provision", json=req_payload, headers=headers)
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["operation_id"] == req_payload["operation_id"]
        assert data2["status"] == "provisioned"
        assert data2["replayed_flag"] is True
        assert data2["device_id"] == first_device_id
        assert data2["created_at"] == data1["created_at"]

        # 3. Third call: query by operation_id -> 200 OK
        resp_query = await ac.get(
            f"/api/internal/v1/devices/provision/by-operation/{req_payload['operation_id']}",
            headers=headers,
        )
        assert resp_query.status_code == 200
        data_query = resp_query.json()
        assert data_query["operation_id"] == req_payload["operation_id"]
        assert data_query["device_id"] == first_device_id
        assert data_query["replayed_flag"] is True

        # 4. Fourth call: query by SN -> 200 OK
        resp_sn = await ac.get(
            f"/api/internal/v1/devices/provision/by-sn/{req_payload['sn']}",
            headers=headers,
        )
        assert resp_sn.status_code == 200
        assert resp_sn.json()["device_id"] == first_device_id

    # Verify underlying DB entities
    assert req_payload["operation_id"] in session.provisionings
    assert "SN-IDEM-001" in session.devices
    assert 10 in session.orgs
    assert first_device_id in session.binds
    assert first_device_id in session.connections
    assert len(session.audit_logs) == 1
    assert len(session.events) == 1
    assert session.events[0].event_type == RemoteSessionEventType.DEVICE_PROVISIONED


@pytest.mark.asyncio
async def test_reused_operation_id_different_payload_conflict(app_with_in_memory_db, monkeypatch):
    """Reusing operation_id with differing parameters raises 409 Conflict (OPERATION_ID_CONFLICT)."""
    app, _ = app_with_in_memory_db
    monkeypatch.setattr(settings.auth, "internal_service_key", "sec-prov-key")
    headers = {"X-Internal-Service-Key": "sec-prov-key"}

    op_id = "018f3a5b-0006-7001-8000-000000000002"
    base_payload = {
        "operation_id": op_id,
        "contract_version": "1.0.0",
        "tenant_id": 10,
        "terminal_id": 101,
        "sn": "SN-DIFF-001",
        "metadata": {"firmware": "1.0"},
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Initial provisioning succeeds
        resp1 = await ac.post("/api/internal/v1/devices/provision", json=base_payload, headers=headers)
        assert resp1.status_code == 201

        # Conflict 1: change terminal_id with same operation_id
        mutated_payload_1 = dict(base_payload, terminal_id=999)
        resp_conf1 = await ac.post("/api/internal/v1/devices/provision", json=mutated_payload_1, headers=headers)
        assert resp_conf1.status_code == 409
        err1 = resp_conf1.json()["detail"]
        assert err1["error_code"] == "OPERATION_ID_CONFLICT"

        # Conflict 2: change tenant_id with same operation_id
        mutated_payload_2 = dict(base_payload, tenant_id=20)
        resp_conf2 = await ac.post("/api/internal/v1/devices/provision", json=mutated_payload_2, headers=headers)
        assert resp_conf2.status_code == 409
        assert resp_conf2.json()["detail"]["error_code"] == "OPERATION_ID_CONFLICT"

        # Conflict 3: change sn with same operation_id
        mutated_payload_3 = dict(base_payload, sn="SN-DIFF-999")
        resp_conf3 = await ac.post("/api/internal/v1/devices/provision", json=mutated_payload_3, headers=headers)
        assert resp_conf3.status_code == 409
        assert resp_conf3.json()["detail"]["error_code"] == "OPERATION_ID_CONFLICT"


@pytest.mark.asyncio
async def test_identity_conflicts(app_with_in_memory_db, monkeypatch):
    """Validates identity conflict protections:

    1. SN registered to another tenant cannot be claimed (cross-tenant SN hijacking rejected).
    2. Terminal ID already provisioned in tenant cannot be silently overwritten with a different SN.
    3. Explicit device_id clashing with another device is rejected.
    """
    app, session = app_with_in_memory_db
    monkeypatch.setattr(settings.auth, "internal_service_key", "sec-prov-key")
    headers = {"X-Internal-Service-Key": "sec-prov-key"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Provision SN-TENANT-A for tenant 1
        resp_a = await ac.post(
            "/api/internal/v1/devices/provision",
            headers=headers,
            json={
                "operation_id": "018f3a5b-0006-7001-8000-000000000010",
                "tenant_id": 1,
                "terminal_id": 100,
                "sn": "SN-TENANT-A",
            },
        )
        assert resp_a.status_code == 201

        # Attempt 1: Tenant 2 tries to provision the same SN-TENANT-A
        resp_hijack = await ac.post(
            "/api/internal/v1/devices/provision",
            headers=headers,
            json={
                "operation_id": "018f3a5b-0006-7001-8000-000000000011",
                "tenant_id": 2,
                "terminal_id": 200,
                "sn": "SN-TENANT-A",
            },
        )
        assert resp_hijack.status_code == 409
        err_hijack = resp_hijack.json()["detail"]
        assert err_hijack["error_code"] == "IDENTITY_CONFLICT"
        assert "different tenant" in err_hijack["message"] or "already provisioned" in err_hijack["message"]

        # Attempt 2: Tenant 1 tries to provision terminal 100 with a DIFFERENT serial number
        resp_term_clash = await ac.post(
            "/api/internal/v1/devices/provision",
            headers=headers,
            json={
                "operation_id": "018f3a5b-0006-7001-8000-000000000012",
                "tenant_id": 1,
                "terminal_id": 100,
                "sn": "SN-TENANT-A-MUTATED",
            },
        )
        assert resp_term_clash.status_code == 409
        err_term = resp_term_clash.json()["detail"]
        assert err_term["error_code"] == "IDENTITY_CONFLICT"
        assert "already provisioned with serial number" in err_term["message"]

        # Attempt 3: Explicit device_id clash with another device
        first_dev_id = resp_a.json()["device_id"]
        resp_dev_id_clash = await ac.post(
            "/api/internal/v1/devices/provision",
            headers=headers,
            json={
                "operation_id": "018f3a5b-0006-7001-8000-000000000013",
                "tenant_id": 1,
                "terminal_id": 105,
                "sn": "SN-NEW-DEV-001",
                "device_id": first_dev_id,
            },
        )
        assert resp_dev_id_clash.status_code == 409
        assert resp_dev_id_clash.json()["detail"]["error_code"] == "IDENTITY_CONFLICT"


@pytest.mark.asyncio
async def test_tenant_isolation(app_with_in_memory_db, monkeypatch):
    """Validates that distinct tenants have isolated terminal IDs, devices, and mappings."""
    app, session = app_with_in_memory_db
    monkeypatch.setattr(settings.auth, "internal_service_key", "sec-prov-key")
    headers = {"X-Internal-Service-Key": "sec-prov-key"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Tenant 100 has terminal 1
        resp_t100 = await ac.post(
            "/api/internal/v1/devices/provision",
            headers=headers,
            json={
                "operation_id": "018f3a5b-0006-7001-8000-000000000100",
                "tenant_id": 100,
                "terminal_id": 1,
                "sn": "SN-T100-T1",
            },
        )
        assert resp_t100.status_code == 201

        # Tenant 200 ALSO has terminal 1 (same terminal_id number, but different tenant and SN)
        resp_t200 = await ac.post(
            "/api/internal/v1/devices/provision",
            headers=headers,
            json={
                "operation_id": "018f3a5b-0006-7001-8000-000000000200",
                "tenant_id": 200,
                "terminal_id": 1,
                "sn": "SN-T200-T1",
            },
        )
        assert resp_t200.status_code == 201

        # Ensure both are provisioned independently with different device IDs
        d1 = resp_t100.json()
        d2 = resp_t200.json()
        assert d1["device_id"] != d2["device_id"]
        assert session.binds[d1["device_id"]].org_id == 100
        assert session.binds[d2["device_id"]].org_id == 200


@pytest.mark.asyncio
async def test_concurrent_requests_handling(app_with_in_memory_db, monkeypatch):
    """Simultaneous concurrent requests with identical operation_id resolve cleanly without crashing."""
    app, _ = app_with_in_memory_db
    monkeypatch.setattr(settings.auth, "internal_service_key", "sec-prov-key")
    headers = {"X-Internal-Service-Key": "sec-prov-key"}

    req_payload = {
        "operation_id": "018f3a5b-0006-7001-8000-000000000300",
        "tenant_id": 5,
        "terminal_id": 50,
        "sn": "SN-CONCURRENT-01",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        tasks = [
            ac.post("/api/internal/v1/devices/provision", json=req_payload, headers=headers)
            for _ in range(5)
        ]
        responses = await asyncio.gather(*tasks)

        status_codes = [r.status_code for r in responses]
        assert all(code in (200, 201) for code in status_codes)
        # Exactly one must be 201 Created (or if lock serializes, first is 201 and others 200)
        assert 201 in status_codes
        device_ids = {r.json()["device_id"] for r in responses}
        assert len(device_ids) == 1


@pytest.mark.asyncio
async def test_restart_persistence_and_replay(app_with_in_memory_db, monkeypatch):
    """Simulates restart resilience: data committed in DB persists across service restarts."""
    app, session = app_with_in_memory_db
    monkeypatch.setattr(settings.auth, "internal_service_key", "sec-prov-key")
    headers = {"X-Internal-Service-Key": "sec-prov-key"}

    op_id = "018f3a5b-0006-7001-8000-000000000400"
    payload = {
        "operation_id": op_id,
        "tenant_id": 8,
        "terminal_id": 80,
        "sn": "SN-RESTART-01",
    }

    # 1. Provision before restart
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r1 = await ac.post("/api/internal/v1/devices/provision", json=payload, headers=headers)
        assert r1.status_code == 201
        assigned_dev_id = r1.json()["device_id"]

    # 2. Simulate restart: create new service instance, but pointing to the same persistent DB session
    new_service = DeviceProvisioningService()
    monkeypatch.setattr("api.internal_v1.device_provisioning.device_provisioning_service", new_service)

    # 3. Request after restart with same operation_id -> must return 200 OK with replayed_flag=True
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r2 = await ac.post("/api/internal/v1/devices/provision", json=payload, headers=headers)
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["replayed_flag"] is True
        assert data2["device_id"] == assigned_dev_id
        assert data2["operation_id"] == op_id

        # Query after restart
        r_get = await ac.get(f"/api/internal/v1/devices/provision/by-operation/{op_id}", headers=headers)
        assert r_get.status_code == 200
        assert r_get.json()["device_id"] == assigned_dev_id


@pytest.mark.asyncio
async def test_event_emission_and_feed_integration(app_with_in_memory_db, monkeypatch):
    """Durable provisioning facts are published into tb_remote_session_events feed."""
    app, session = app_with_in_memory_db
    monkeypatch.setattr(settings.auth, "internal_service_key", "sec-prov-key")
    headers = {"X-Internal-Service-Key": "sec-prov-key"}

    op_id = "018f3a5b-0006-7001-8000-000000000500"
    payload = {
        "operation_id": op_id,
        "tenant_id": 3,
        "terminal_id": 30,
        "sn": "SN-EVT-01",
        "correlation_id": "corr-evt-500",
        "metadata": {"firmware": "2.1.0"},
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/internal/v1/devices/provision", json=payload, headers=headers)
        assert resp.status_code == 201
        dev_id = resp.json()["device_id"]

    # Check event in session
    assert len(session.events) == 1
    ev = session.events[0]
    assert ev.event_type == RemoteSessionEventType.DEVICE_PROVISIONED
    assert ev.sn == "SN-EVT-01"
    assert ev.tenant_id == 3
    assert ev.terminal_id == "30"
    assert ev.device_id == dev_id
    assert ev.operation_id == op_id
    assert ev.correlation_id == "corr-evt-500"
    assert ev.lifecycle_state == "provisioned"
    assert ev.reason == "provisioned_successfully"
    assert ev.cursor >= 1

    # Verify no commercial fields in payload
    validate_no_commercial_fields(ev.payload)
    assert ev.payload["operation_id"] == op_id
    assert ev.payload["status"] == "provisioned"


@pytest.mark.asyncio
async def test_auth_and_error_schema(app_with_in_memory_db, monkeypatch):
    """Validates service authentication requirements and structured error schema."""
    app, _ = app_with_in_memory_db
    monkeypatch.setattr(settings.auth, "internal_service_key", "sec-prov-key")

    payload = {
        "operation_id": "018f3a5b-0006-7001-8000-000000000600",
        "tenant_id": 1,
        "terminal_id": 10,
        "sn": "SN-AUTH-01",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Missing credentials -> 403 Forbidden
        r_no_auth = await ac.post("/api/internal/v1/devices/provision", json=payload)
        assert r_no_auth.status_code == 403

        # 2. Invalid credentials -> 403 Forbidden
        r_bad_auth = await ac.post(
            "/api/internal/v1/devices/provision",
            json=payload,
            headers={"X-Internal-Service-Key": "wrong-key"},
        )
        assert r_bad_auth.status_code == 403

        # 3. Valid Bearer auth -> 201 Created
        r_bearer = await ac.post(
            "/api/internal/v1/devices/provision",
            json=payload,
            headers={"Authorization": "Bearer sec-prov-key"},
        )
        assert r_bearer.status_code == 201

        # 4. Invalid SN pattern -> 422 Unprocessable Entity
        r_bad_sn = await ac.post(
            "/api/internal/v1/devices/provision",
            json=dict(payload, operation_id="018f3a5b-0006-7001-8000-000000000601", sn="bad!sn@#$"),
            headers={"Authorization": "Bearer sec-prov-key"},
        )
        assert r_bad_sn.status_code == 422

        # 5. Invalid commercial fields in metadata -> 422
        r_comm = await ac.post(
            "/api/internal/v1/devices/provision",
            json=dict(
                payload,
                operation_id="018f3a5b-0006-7001-8000-000000000602",
                sn="SN-COMM-01",
                metadata={"tariff_price": 500},
            ),
            headers={"Authorization": "Bearer sec-prov-key"},
        )
        assert r_comm.status_code == 422

        # 6. Query non-existent operation_id -> 404
        r_404 = await ac.get(
            "/api/internal/v1/devices/provision/by-operation/018f3a5b-0006-7001-8000-999999999999",
            headers={"Authorization": "Bearer sec-prov-key"},
        )
        assert r_404.status_code == 404
        err_404 = r_404.json()["detail"]
        assert err_404["error_code"] == "OPERATION_NOT_FOUND"


@pytest.mark.asyncio
async def test_generate_and_verify_contract_artifacts():
    """Generates and validates immutable OpenAPI specification, JSON schemas, and golden fixtures."""
    repo_root = Path(__file__).parent.parent.parent.parent
    schemas_dir = repo_root / "docs" / "l4desk" / "contracts" / "schemas"
    fixtures_dir = repo_root / "docs" / "l4desk" / "fixtures"

    schemas_dir.mkdir(parents=True, exist_ok=True)
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    # 1. Generate OpenAPI specification for Internal API
    internal_app = FastAPI(
        title="L4Desk Device Provisioning Internal API",
        version="1.0.0",
        description="Versioned internal REST contract for idempotent device and terminal provisioning",
    )
    internal_app.include_router(device_provisioning_router, prefix="/api/internal/v1")
    openapi_spec = get_openapi(
        title=internal_app.title,
        version=internal_app.version,
        openapi_version="3.1.0",
        description=internal_app.description,
        routes=internal_app.routes,
    )
    openapi_path = schemas_dir / "device_provisioning_openapi.json"
    with open(openapi_path, "w", encoding="utf-8") as f:
        json.dump(openapi_spec, f, indent=2, ensure_ascii=False)
    assert openapi_path.exists() and openapi_path.stat().st_size > 0
    assert "/api/internal/v1/devices/provision" in openapi_spec["paths"]
    assert "/api/internal/v1/devices/provision/by-operation/{operation_id}" in openapi_spec["paths"]

    # 2. Generate JSON Schema for DeviceProvisionRequest
    req_schema_path = schemas_dir / "device_provision_request.schema.json"
    req_schema = DeviceProvisionRequest.model_json_schema()
    req_schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    with open(req_schema_path, "w", encoding="utf-8") as f:
        json.dump(req_schema, f, indent=2, ensure_ascii=False)
    assert req_schema_path.exists() and req_schema_path.stat().st_size > 0

    # 3. Generate JSON Schema for DeviceProvisionResponse
    resp_schema_path = schemas_dir / "device_provision_response.schema.json"
    resp_schema = DeviceProvisionResponse.model_json_schema()
    resp_schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    with open(resp_schema_path, "w", encoding="utf-8") as f:
        json.dump(resp_schema, f, indent=2, ensure_ascii=False)
    assert resp_schema_path.exists() and resp_schema_path.stat().st_size > 0

    # 4. Validate Golden Examples
    fixtures_path = fixtures_dir / "device_provisioning_examples_v1.json"
    assert fixtures_path.exists()
    with open(fixtures_path, "r", encoding="utf-8") as f:
        fixtures_data = json.load(f)

    examples = fixtures_data["examples"]
    req_example = DeviceProvisionRequest.model_validate(examples["provision_request_initial"])
    assert req_example.operation_id == "018f3a5b-0006-7001-8000-000000000001"
    assert req_example.sn == "SNPROV001"

    resp_created = DeviceProvisionResponse.model_validate(examples["provision_response_created_201"])
    assert resp_created.status == DeviceProvisionStatus.PROVISIONED
    assert resp_created.replayed_flag is False

    resp_replayed = DeviceProvisionResponse.model_validate(examples["provision_response_replayed_200"])
    assert resp_replayed.status == DeviceProvisionStatus.PROVISIONED
    assert resp_replayed.replayed_flag is True

    # Validate event feed fact fixture
    event_fact = examples["provision_event_feed_fact"]
    assert event_fact["event_type"] == "device_provisioned"
    validate_no_commercial_fields(event_fact["payload"])
