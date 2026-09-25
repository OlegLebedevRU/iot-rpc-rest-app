from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
from typing import Any
from unittest.mock import AsyncMock
from sqlalchemy import select

import pytest
from httpx import ASGITransport, AsyncClient

from core.config import settings
from core.models import db_helper
from core.models.remote_sessions import RemoteSession, RemoteSessionEvent
from core.schemas.remote_sessions import (
    FORBIDDEN_EVENT_COMMERCIAL_FIELDS,
    RemoteSessionCreate,
    RemoteSessionEventFeedResponse,
    RemoteSessionEventItem,
    RemoteSessionEventType,
    RemoteSessionLifecycleState,
    RemoteSessionReconciliationResponse,
    RemoteSessionResponse,
    RemoteSessionStop,
    RemoteSessionType,
    validate_no_commercial_fields,
)
from core.services.remote_session_event_service import (
    RemoteSessionEventService,
    remote_session_event_service,
)
from main import main_app


class InMemoryAsyncSession:
    """Mock AsyncSession with in-memory persistence for events and sessions."""

    def __init__(self) -> None:
        self.events: list[RemoteSessionEvent] = []
        self.sessions: dict[str, RemoteSession] = {}
        self._next_cursor = 1
        self._next_sess_id = 1
        self._lock = asyncio.Lock()

    def add(self, obj: Any) -> None:
        if isinstance(obj, RemoteSessionEvent):
            if obj.cursor is None:
                obj.cursor = self._next_cursor
                self._next_cursor += 1
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime.now(UTC)
            self.events.append(obj)
        elif isinstance(obj, RemoteSession):
            if obj.id is None:
                obj.id = self._next_sess_id
                self._next_sess_id += 1
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime.now(UTC)
            self.sessions[obj.session_id] = obj

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def refresh(self, obj: Any) -> None:
        pass

    async def scalar(self, stmt: Any) -> Any:
        where_criteria = getattr(stmt, "_where_criteria", ())
        target_event_id = None
        target_op_id = None
        target_sess_id = None

        for criterion in where_criteria:
            if hasattr(criterion, "left") and hasattr(criterion, "right"):
                col_name = getattr(criterion.left, "key", None) or getattr(criterion.left, "name", None)
                val = getattr(criterion.right, "value", None)
                if col_name == "event_id":
                    target_event_id = val
                elif col_name == "operation_id":
                    target_op_id = val
                elif col_name == "session_id":
                    target_sess_id = val

        stmt_str = str(stmt).lower()
        if "tb_remote_session_events" in stmt_str or "event" in stmt_str:
            if target_event_id is not None:
                for ev in self.events:
                    if ev.event_id == target_event_id:
                        return ev
            if target_op_id is not None:
                for ev in self.events:
                    if ev.operation_id == target_op_id:
                        return ev

        if "tb_remote_sessions" in stmt_str or "session" in stmt_str:
            if target_op_id is not None:
                for s in self.sessions.values():
                    if s.operation_id == target_op_id:
                        return s
            if target_sess_id is not None:
                if target_sess_id in self.sessions:
                    return self.sessions[target_sess_id]

        try:
            params = stmt.compile().params
        except Exception:
            params = {}

        for p in params.values():
            for ev in self.events:
                if ev.event_id == p or ev.operation_id == p:
                    return ev
            for s in self.sessions.values():
                if s.operation_id == p or s.session_id == p:
                    return s

        return None

    async def scalars(self, stmt: Any) -> Any:
        class Result:
            def __init__(self, items: list[Any]) -> None:
                self._items = items

            def all(self) -> list[Any]:
                return self._items

        # Handle get_event_feed query
        params = stmt.compile().params
        after_cursor = 0
        for k, v in params.items():
            if "cursor" in k and isinstance(v, int):
                after_cursor = v
                break

        filtered = [ev for ev in self.events if ev.cursor > after_cursor]
        filtered.sort(key=lambda ev: ev.cursor)

        limit_val = 101
        for k, v in params.items():
            if "param" in k or "limit" in k:
                if isinstance(v, int) and v > 0:
                    limit_val = v
                    break

        return Result(filtered[:limit_val])

    async def execute(self, stmt: Any) -> Any:
        class ExecResult:
            def __init__(self, rows: list[Any]) -> None:
                self._rows = rows

            def first(self) -> Any:
                return self._rows[0] if self._rows else None

            def all(self) -> list[Any]:
                return self._rows

        stmt_str = str(stmt).lower()
        if "count" in stmt_str and "min" in stmt_str:
            count = len(self.events)
            min_c = min((e.cursor for e in self.events), default=None)
            max_c = max((e.cursor for e in self.events), default=None)
            return ExecResult([(count, min_c, max_c)])

        if "group by tb_remote_session_events.event_type" in stmt_str or "group_by" in stmt_str:
            counts: dict[str, int] = {}
            for e in self.events:
                counts[e.event_type] = counts.get(e.event_type, 0) + 1
            return ExecResult([(k, v) for k, v in counts.items()])

        if "group by tb_remote_sessions.status" in stmt_str:
            counts_s: dict[str, int] = {}
            for s in self.sessions.values():
                counts_s[s.status] = counts_s.get(s.status, 0) + 1
            return ExecResult([(k, v) for k, v in counts_s.items()])

        if "tb_remote_session_events.cursor" in stmt_str and "tb_remote_session_events.event_id" in stmt_str:
            # SHA hash items query
            sorted_events = sorted(self.events, key=lambda e: e.cursor)
            rows = [
                (e.cursor, e.event_id, e.event_type, e.occurred_at)
                for e in sorted_events[:5000]
            ]
            return ExecResult(rows)

        # Fallback for device/tenant resolution
        return ExecResult([(1, 10)])


@pytest.mark.asyncio
async def test_all_nine_mandatory_events_recording():
    """Verify recording of all 9 mandatory event types from Architecture section 6.1."""
    session = InMemoryAsyncSession()
    service = RemoteSessionEventService()

    # 1. device_online
    ev1 = await service.record_device_online(
        session, sn="SN1001", tenant_id=1, terminal_id="term-1"
    )
    assert ev1.event_type == RemoteSessionEventType.DEVICE_ONLINE
    assert ev1.cursor == 1
    assert ev1.lifecycle_state == "online"

    # 2. remote_session_start_requested
    ev2 = await service.record_session_start_requested(
        session,
        session_id="sess-c-1",
        sn="SN1001",
        session_type="console",
        tenant_id=1,
        terminal_id="term-1",
        requested_by_user_id="user-1",
    )
    assert ev2.event_type == RemoteSessionEventType.REMOTE_SESSION_START_REQUESTED
    assert ev2.cursor == 2
    assert ev2.lifecycle_state == RemoteSessionLifecycleState.REQUESTED
    assert ev2.payload.get("requested_by_user_id") == "user-1"

    # 3. remote_session_active
    ev3 = await service.record_session_active(
        session, session_id="sess-c-1", sn="SN1001", session_type="console"
    )
    assert ev3.event_type == RemoteSessionEventType.REMOTE_SESSION_ACTIVE
    assert ev3.cursor == 3
    assert ev3.lifecycle_state == RemoteSessionLifecycleState.ACTIVE

    # 4. console_command_started
    ev4 = await service.record_console_command_started(
        session, sn="SN1001", command_id="system_info", session_id="sess-c-1"
    )
    assert ev4.event_type == RemoteSessionEventType.CONSOLE_COMMAND_STARTED
    assert ev4.cursor == 4
    assert ev4.payload.get("command_id") == "system_info"

    # 5. console_command_completed
    ev5 = await service.record_console_command_completed(
        session, sn="SN1001", command_id="system_info", exit_code=0, session_id="sess-c-1"
    )
    assert ev5.event_type == RemoteSessionEventType.CONSOLE_COMMAND_COMPLETED
    assert ev5.cursor == 5
    assert ev5.payload.get("exit_code") == 0

    # 6. console_command_timed_out
    ev6 = await service.record_console_command_timed_out(
        session, sn="SN1001", command_id="long_job", session_id="sess-c-1"
    )
    assert ev6.event_type == RemoteSessionEventType.CONSOLE_COMMAND_TIMED_OUT
    assert ev6.cursor == 6
    assert ev6.payload.get("timeout") is True

    # 7. remote_session_stop_requested
    ev7 = await service.record_session_stop_requested(
        session, session_id="sess-c-1", sn="SN1001", session_type="console", reason="user_stop"
    )
    assert ev7.event_type == RemoteSessionEventType.REMOTE_SESSION_STOP_REQUESTED
    assert ev7.cursor == 7
    assert ev7.reason == "user_stop"

    # 8. remote_session_closed
    ev8 = await service.record_session_closed(
        session, session_id="sess-c-1", sn="SN1001", session_type="console", reason="graceful"
    )
    assert ev8.event_type == RemoteSessionEventType.REMOTE_SESSION_CLOSED
    assert ev8.cursor == 8

    # 9. remote_session_failed
    ev9 = await service.record_session_failed(
        session, session_id="sess-c-2", sn="SN1001", session_type="console", reason="timeout"
    )
    assert ev9.event_type == RemoteSessionEventType.REMOTE_SESSION_FAILED
    assert ev9.cursor == 9

    # Monotonicity check
    cursors = [e.cursor for e in session.events]
    assert cursors == list(range(1, 10))
    assert len(session.events) == 9


@pytest.mark.asyncio
async def test_duplicate_delivery_and_idempotency():
    """Verify idempotency on duplicate event_id and duplicate operation_id."""
    session = InMemoryAsyncSession()
    service = RemoteSessionEventService()

    # Record first event
    e1 = await service.record_event(
        session,
        event_type="device_online",
        sn="SN1001",
        event_id="evt_fixed_001",
        operation_id="op_fix_001",
    )
    assert e1.cursor == 1
    assert len(session.events) == 1

    # Re-deliver exact same event_id
    e2 = await service.record_event(
        session,
        event_type="device_online",
        sn="SN1001",
        event_id="evt_fixed_001",
    )
    # Must return existing event and not append duplicate
    assert e2.cursor == 1
    assert len(session.events) == 1

    # Re-deliver with same operation_id and event_type
    e3 = await service.record_event(
        session,
        event_type="device_online",
        sn="SN1001",
        operation_id="op_fix_001",
    )
    assert e3.cursor == 1
    assert len(session.events) == 1


@pytest.mark.asyncio
async def test_forbidden_commercial_fields_rejection():
    """Verify that financial/billing terms are strictly rejected from IoT event payloads."""
    session = InMemoryAsyncSession()
    service = RemoteSessionEventService()

    for forbidden in ["billing", "price", "tariff", "balance", "cost", "invoice", "subledger"]:
        with pytest.raises(ValueError) as exc:
            await service.record_event(
                session,
                event_type="device_online",
                sn="SN1001",
                payload={"data": {forbidden: 100}},
            )
        assert "Commercial or billing field" in str(exc.value)


@pytest.mark.asyncio
async def test_event_feed_pagination_and_resume():
    """Verify monotonic cursor pagination, limit handling, and resume capability."""
    session = InMemoryAsyncSession()
    service = RemoteSessionEventService()

    # Seed 5 events
    for i in range(1, 6):
        await service.record_event(
            session,
            event_type="console_command_started",
            sn="SN1001",
            payload={"cmd_index": i},
        )
    assert len(session.events) == 5

    # Page 1: after=0, limit=2
    page1 = await service.get_event_feed(session, after=0, limit=2)
    assert len(page1.items) == 2
    assert page1.items[0].cursor == 1
    assert page1.items[1].cursor == 2
    assert page1.next_cursor == 2
    assert page1.has_more is True

    # Page 2: after=page1.next_cursor, limit=2
    page2 = await service.get_event_feed(session, after=page1.next_cursor, limit=2)
    assert len(page2.items) == 2
    assert page2.items[0].cursor == 3
    assert page2.items[1].cursor == 4
    assert page2.next_cursor == 4
    assert page2.has_more is True

    # Page 3: resume after=4, limit=2
    page3 = await service.get_event_feed(session, after=page2.next_cursor, limit=2)
    assert len(page3.items) == 1
    assert page3.items[0].cursor == 5
    assert page3.next_cursor == 5
    assert page3.has_more is False

    # Page 4: after=5 (at boundary) -> empty page, has_more=False
    page4 = await service.get_event_feed(session, after=5, limit=2)
    assert len(page4.items) == 0
    assert page4.next_cursor == 5
    assert page4.has_more is False


@pytest.mark.asyncio
async def test_invalid_cursor_and_limit_parameters():
    """Verify that invalid cursor or limit parameters raise ValueError."""
    session = InMemoryAsyncSession()
    service = RemoteSessionEventService()

    with pytest.raises(ValueError) as exc:
        await service.get_event_feed(session, after=-1, limit=10)
    assert "Parameter 'after' must be a non-negative integer" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        await service.get_event_feed(session, after=0, limit=0)
    assert "Parameter 'limit' must be between 1 and 1000" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        await service.get_event_feed(session, after=0, limit=1001)
    assert "Parameter 'limit' must be between 1 and 1000" in str(exc.value)


@pytest.mark.asyncio
async def test_reconciliation_summary_and_sha256():
    """Verify reconciliation summary aggregates and deterministic SHA-256 digest."""
    session = InMemoryAsyncSession()
    service = RemoteSessionEventService()

    await service.record_device_online(session, sn="SN1001", tenant_id=1)
    await service.record_session_start_requested(
        session, session_id="sess-1", sn="SN1001", session_type="console", tenant_id=1
    )

    recon = await service.get_reconciliation_summary(session, tenant_id=1)
    assert recon.total_events == 2
    assert recon.min_cursor == 1
    assert recon.max_cursor == 2
    assert len(recon.feed_sha256) == 64  # SHA-256 hex string

    # Adding a new event must deterministically change feed_sha256
    digest_before = recon.feed_sha256
    await service.record_session_closed(
        session, session_id="sess-1", sn="SN1001", session_type="console", tenant_id=1
    )
    recon_after = await service.get_reconciliation_summary(session, tenant_id=1)
    assert recon_after.total_events == 3
    assert recon_after.max_cursor == 3
    assert recon_after.feed_sha256 != digest_before


@pytest.mark.asyncio
async def test_concurrent_writers_monotonic_integrity():
    """Verify that multiple concurrent event writes generate distinct monotonic cursors without conflict."""
    session = InMemoryAsyncSession()
    service = RemoteSessionEventService()

    async def write_event(idx: int):
        return await service.record_event(
            session,
            event_type="console_command_started",
            sn=f"SN_{idx}",
            payload={"task_idx": idx},
        )

    tasks = [write_event(i) for i in range(20)]
    results = await asyncio.gather(*tasks)

    cursors = [r.cursor for r in results]
    assert len(cursors) == 20
    assert len(set(cursors)) == 20  # All unique!
    assert min(cursors) == 1
    assert max(cursors) == 20


# ─────────────────────────────────────────────────────────────────────────────
# 2. REST API Integration Tests (FastAPI Client, Authentication, Endpoints)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_auth_protection_and_headers():
    """Verify REST API authorization enforcement on /api/internal/v1/ endpoints."""
    transport = ASGITransport(app=main_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. No auth headers -> 403 Forbidden
        resp_no_auth = await client.get("/api/internal/v1/remote-session-events")
        assert resp_no_auth.status_code == 403

        # 2. Invalid auth header -> 403 Forbidden
        resp_bad_auth = await client.get(
            "/api/internal/v1/remote-session-events",
            headers={"X-Internal-Service-Key": "wrong_key"},
        )
        assert resp_bad_auth.status_code == 403

        # 3. Valid auth header -> 200 OK (with mocked session)
        fake_session = InMemoryAsyncSession()
        async def fake_session_getter():
            yield fake_session

        main_app.dependency_overrides[db_helper.session_getter] = fake_session_getter
        try:
            resp_ok = await client.get(
                "/api/internal/v1/remote-session-events",
                headers={"X-Internal-Service-Key": "test"},
            )
            assert resp_ok.status_code == 200
            data = resp_ok.json()
            assert "items" in data
            assert "next_cursor" in data
            assert "has_more" in data
            assert "total_count" in data
            assert "server_time" in data
        finally:
            main_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_remote_session_lifecycle_and_idempotency():
    """Verify POST /remote-sessions, GET /remote-sessions/{id}, and POST /remote-sessions/{id}/stop."""
    fake_session = InMemoryAsyncSession()
    async def fake_session_getter():
        yield fake_session

    main_app.dependency_overrides[db_helper.session_getter] = fake_session_getter
    headers = {
        "X-Internal-Service-Key": "test",
        "X-Org-Id": "1",
        "X-Role": "superuser",
    }
    transport = ASGITransport(app=main_app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Create Session
            create_payload = {
                "operation_id": "018f3a5b-0001-7001-8000-000000000001",
                "contract_version": "1.0.0",
                "tenant_id": 1,
                "terminal_id": "term-test-1",
                "sn": "SNTEST01",
                "session_type": "console",
                "requested_by_user_id": "user-42",
                "correlation_id": "corr-001",
                "session_metadata": {"client": "web-shell"},
            }
            resp_create = await client.post(
                "/api/internal/v1/remote-sessions",
                headers=headers,
                json=create_payload,
            )
            assert resp_create.status_code == 201
            session_data = resp_create.json()
            sess_id = session_data["session_id"]
            assert session_data["status"] == "requested"
            assert session_data["sn"] == "SNTEST01"
            assert session_data["tenant_id"] == 1

            # 2. Idempotent Create: Same operation_id returns identical session
            resp_dup = await client.post(
                "/api/internal/v1/remote-sessions",
                headers=headers,
                json=create_payload,
            )
            assert resp_dup.status_code == 201
            assert resp_dup.json()["session_id"] == sess_id

            # 3. GET Session Facts
            resp_get = await client.get(
                f"/api/internal/v1/remote-sessions/{sess_id}",
                headers=headers,
            )
            assert resp_get.status_code == 200
            assert resp_get.json()["session_id"] == sess_id

            # 4. Stop Session
            resp_stop = await client.post(
                f"/api/internal/v1/remote-sessions/{sess_id}/stop",
                headers=headers,
                json={"reason": "normal_exit", "operation_id": "op-stop-001"},
            )
            assert resp_stop.status_code == 200
            assert resp_stop.json()["status"] == "closed"
            assert resp_stop.json()["close_reason"] == "normal_exit"

            # 5. Non-existent Session -> 404
            resp_404 = await client.get(
                "/api/internal/v1/remote-sessions/sess-nonexistent",
                headers=headers,
            )
            assert resp_404.status_code == 404
    finally:
        main_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_openapi_schema_compatibility():
    """Verify OpenAPI and JSON Schema definitions for remote session events and facts."""
    from fastapi import FastAPI
    from api.internal_v1.remote_sessions import router as remote_sessions_router

    # Build internal OpenAPI schema
    internal_app = FastAPI(title="L4Desk Internal API", version="1.0.0")
    internal_app.include_router(remote_sessions_router, prefix="/api/internal/v1")
    openapi = internal_app.openapi()
    paths = openapi.get("paths", {})

    assert "/api/internal/v1/remote-session-events" in paths
    assert "/api/internal/v1/remote-session-events/reconciliation" in paths
    assert "/api/internal/v1/remote-sessions" in paths
    assert "/api/internal/v1/remote-sessions/{session_id}" in paths
    assert "/api/internal/v1/remote-sessions/{session_id}/stop" in paths

    # Verify query parameters in feed endpoint schema
    feed_get = paths["/api/internal/v1/remote-session-events"]["get"]
    param_names = [p["name"] for p in feed_get.get("parameters", [])]
    assert "after" in param_names
    assert "limit" in param_names
    assert "tenant_id" in param_names
    assert "sn" in param_names

    # Verify JSON Schema generation
    event_schema = RemoteSessionEventItem.model_json_schema()
    assert "cursor" in event_schema["properties"]
    assert "event_id" in event_schema["properties"]
    assert "occurred_at" in event_schema["properties"]
    assert "lifecycle_state" in event_schema["properties"]

    feed_schema = RemoteSessionEventFeedResponse.model_json_schema()
    assert "items" in feed_schema["properties"]
    assert "next_cursor" in feed_schema["properties"]
    assert "has_more" in feed_schema["properties"]
    assert "server_time" in feed_schema["properties"]

    recon_schema = RemoteSessionReconciliationResponse.model_json_schema()
    assert "feed_sha256" in recon_schema["properties"]
    assert "total_events" in recon_schema["properties"]
    assert "events_by_type" in recon_schema["properties"]


@pytest.mark.asyncio
async def test_generate_and_verify_contract_artifacts():
    """Generate and verify immutable contract artifacts, OpenAPI schema, JSON schemas, and examples."""
    import json
    from pathlib import Path
    from fastapi import FastAPI
    from fastapi.openapi.utils import get_openapi
    from api.internal_v1.remote_sessions import router as remote_sessions_router

    repo_root = Path(__file__).parent.parent.parent.parent
    contracts_dir = repo_root / "docs" / "l4desk" / "contracts"
    schemas_dir = contracts_dir / "schemas"
    fixtures_dir = repo_root / "docs" / "l4desk" / "fixtures"

    schemas_dir.mkdir(parents=True, exist_ok=True)
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    # 1. Generate OpenAPI specification for Internal API
    internal_app = FastAPI(
        title="L4Desk IoT Event Feed & Remote Sessions Internal API",
        version="1.1.0",
        description="Versioned internal REST contract for durable session facts, idempotent stop, and cursor event feed",
    )
    internal_app.include_router(remote_sessions_router, prefix="/api/internal/v1")
    openapi_spec = get_openapi(
        title=internal_app.title,
        version=internal_app.version,
        openapi_version="3.1.0",
        description=internal_app.description,
        routes=internal_app.routes,
    )

    openapi_path = schemas_dir / "iot_event_feed_openapi.json"
    with open(openapi_path, "w", encoding="utf-8") as f:
        json.dump(openapi_spec, f, indent=2, ensure_ascii=False)
    assert openapi_path.exists() and openapi_path.stat().st_size > 0

    # 2. Generate JSON Schema for RemoteSessionEventItem
    event_schema_path = schemas_dir / "remote_session_event.schema.json"
    with open(event_schema_path, "w", encoding="utf-8") as f:
        json.dump(RemoteSessionEventItem.model_json_schema(), f, indent=2, ensure_ascii=False)
    assert event_schema_path.exists() and event_schema_path.stat().st_size > 0

    # 3. Generate JSON Schema for RemoteSession
    session_schema_path = schemas_dir / "remote_session.schema.json"
    session_definitions = {}
    shared_definitions = {}
    for name, model in (
        ("RemoteSessionCreate", RemoteSessionCreate),
        ("RemoteSessionResponse", RemoteSessionResponse),
        ("RemoteSessionStop", RemoteSessionStop),
    ):
        model_schema = model.model_json_schema()
        shared_definitions.update(model_schema.pop("$defs", {}))
        session_definitions[name] = model_schema
    session_combined_schemas = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "RemoteSessionSchemas",
        "$defs": shared_definitions,
        "definitions": session_definitions,
    }
    with open(session_schema_path, "w", encoding="utf-8") as f:
        json.dump(session_combined_schemas, f, indent=2, ensure_ascii=False)
    assert session_schema_path.exists() and session_schema_path.stat().st_size > 0

    # 4. Generate Golden Examples for all 9 Events + Feed Page + Reconciliation
    base_time = datetime(2026, 9, 17, 22, 0, 0, tzinfo=UTC)
    golden_examples = {
        "contract_version": "1.1.0",
        "schema_revision": "2026-09-25-v2",
        "events": {
            "device_online": {
                "cursor": 1,
                "event_id": "evt_example_001",
                "occurred_at": (base_time + timedelta(seconds=1)).isoformat(),
                "event_type": "device_online",
                "event_version": "1.0.0",
                "tenant_id": 1,
                "terminal_id": "term-test-01",
                "device_id": 1001,
                "sn": "SNTEST01",
                "session_id": None,
                "session_type": None,
                "lifecycle_state": "online",
                "reason": None,
                "operation_id": "op-onl-001",
                "correlation_id": "corr-001",
                "payload": {"channel": "app", "qos": 1, "retain": True},
                "created_at": (base_time + timedelta(seconds=1)).isoformat(),
            },
            "remote_session_start_requested": {
                "cursor": 2,
                "event_id": "evt_example_002",
                "occurred_at": (base_time + timedelta(seconds=2)).isoformat(),
                "event_type": "remote_session_start_requested",
                "event_version": "1.0.0",
                "tenant_id": 1,
                "terminal_id": "term-test-01",
                "device_id": 1001,
                "sn": "SNTEST01",
                "session_id": "sess-console-9001",
                "session_type": "console",
                "lifecycle_state": "requested",
                "reason": None,
                "operation_id": "018f3a5b-0001-7001-8000-000000000001",
                "correlation_id": "corr-002",
                "payload": {"requested_by_user_id": "user-42"},
                "created_at": (base_time + timedelta(seconds=2)).isoformat(),
            },
            "remote_session_active": {
                "cursor": 3,
                "event_id": "evt_example_003",
                "occurred_at": (base_time + timedelta(seconds=3)).isoformat(),
                "event_type": "remote_session_active",
                "event_version": "1.0.0",
                "tenant_id": 1,
                "terminal_id": "term-test-01",
                "device_id": 1001,
                "sn": "SNTEST01",
                "session_id": "sess-console-9001",
                "session_type": "console",
                "lifecycle_state": "active",
                "reason": None,
                "operation_id": "018f3a5b-0001-7001-8000-000000000001",
                "correlation_id": "corr-002",
                "payload": {"stream_state": "running"},
                "created_at": (base_time + timedelta(seconds=3)).isoformat(),
            },
            "console_command_started": {
                "cursor": 4,
                "event_id": "evt_example_004",
                "occurred_at": (base_time + timedelta(seconds=4)).isoformat(),
                "event_type": "console_command_started",
                "event_version": "1.0.0",
                "tenant_id": 1,
                "terminal_id": "term-test-01",
                "device_id": 1001,
                "sn": "SNTEST01",
                "session_id": "sess-console-9001",
                "session_type": "console",
                "lifecycle_state": "executing",
                "reason": None,
                "operation_id": "op-cmd-001",
                "correlation_id": "corr-003",
                "payload": {"command_id": "system_info", "shell": "cmd"},
                "created_at": (base_time + timedelta(seconds=4)).isoformat(),
            },
            "console_command_completed": {
                "cursor": 5,
                "event_id": "evt_example_005",
                "occurred_at": (base_time + timedelta(seconds=5)).isoformat(),
                "event_type": "console_command_completed",
                "event_version": "1.0.0",
                "tenant_id": 1,
                "terminal_id": "term-test-01",
                "device_id": 1001,
                "sn": "SNTEST01",
                "session_id": "sess-console-9001",
                "session_type": "console",
                "lifecycle_state": "completed",
                "reason": "exit_code_0",
                "operation_id": "op-cmd-001",
                "correlation_id": "corr-003",
                "payload": {"command_id": "system_info", "exit_code": 0, "bytes_emitted": 256},
                "created_at": (base_time + timedelta(seconds=5)).isoformat(),
            },
            "console_command_timed_out": {
                "cursor": 6,
                "event_id": "evt_example_006",
                "occurred_at": (base_time + timedelta(seconds=6)).isoformat(),
                "event_type": "console_command_timed_out",
                "event_version": "1.0.0",
                "tenant_id": 1,
                "terminal_id": "term-test-01",
                "device_id": 1001,
                "sn": "SNTEST01",
                "session_id": "sess-console-9001",
                "session_type": "console",
                "lifecycle_state": "timed_out",
                "reason": "timeout",
                "operation_id": "op-cmd-002",
                "correlation_id": "corr-004",
                "payload": {"command_id": "ping_infinite", "timeout": True},
                "created_at": (base_time + timedelta(seconds=6)).isoformat(),
            },
            "remote_session_stop_requested": {
                "cursor": 7,
                "event_id": "evt_example_007",
                "occurred_at": (base_time + timedelta(seconds=7)).isoformat(),
                "event_type": "remote_session_stop_requested",
                "event_version": "1.0.0",
                "tenant_id": 1,
                "terminal_id": "term-test-01",
                "device_id": 1001,
                "sn": "SNTEST01",
                "session_id": "sess-console-9001",
                "session_type": "console",
                "lifecycle_state": "stopping",
                "reason": "user_requested",
                "operation_id": "op-stop-001",
                "correlation_id": "corr-005",
                "payload": {},
                "created_at": (base_time + timedelta(seconds=7)).isoformat(),
            },
            "remote_session_closed": {
                "cursor": 8,
                "event_id": "evt_example_008",
                "occurred_at": (base_time + timedelta(seconds=8)).isoformat(),
                "event_type": "remote_session_closed",
                "event_version": "1.0.0",
                "tenant_id": 1,
                "terminal_id": "term-test-01",
                "device_id": 1001,
                "sn": "SNTEST01",
                "session_id": "sess-console-9001",
                "session_type": "console",
                "lifecycle_state": "closed",
                "reason": "normal_exit",
                "operation_id": "op-stop-001",
                "correlation_id": "corr-005",
                "payload": {"duration_sec": 7},
                "created_at": (base_time + timedelta(seconds=8)).isoformat(),
            },
            "remote_session_failed": {
                "cursor": 9,
                "event_id": "evt_example_009",
                "occurred_at": (base_time + timedelta(seconds=9)).isoformat(),
                "event_type": "remote_session_failed",
                "event_version": "1.0.0",
                "tenant_id": 1,
                "terminal_id": "term-test-01",
                "device_id": 1001,
                "sn": "SNTEST01",
                "session_id": "sess-video-9002",
                "session_type": "video",
                "lifecycle_state": "failed",
                "reason": "agent_offline",
                "operation_id": "op-fail-001",
                "correlation_id": "corr-006",
                "payload": {"error": "agent_unreachable"},
                "created_at": (base_time + timedelta(seconds=9)).isoformat(),
            },
        },
        "feed_page_example": {
            "items": [],  # populated in loop
            "next_cursor": 2,
            "has_more": True,
            "total_count": 2,
            "server_time": (base_time + timedelta(seconds=10)).isoformat(),
        },
        "reconciliation_example": {
            "tenant_id": 1,
            "from_cursor": 1,
            "to_cursor": 9,
            "total_events": 9,
            "min_cursor": 1,
            "max_cursor": 9,
            "events_by_type": {
                "device_online": 1,
                "remote_session_start_requested": 1,
                "remote_session_active": 1,
                "console_command_started": 1,
                "console_command_completed": 1,
                "console_command_timed_out": 1,
                "remote_session_stop_requested": 1,
                "remote_session_closed": 1,
                "remote_session_failed": 1,
            },
            "active_sessions_count": 0,
            "sessions_by_status": {"closed": 1, "failed": 1},
            "feed_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "server_time": (base_time + timedelta(seconds=10)).isoformat(),
        },
    }

    golden_examples["feed_page_example"]["items"] = [
        golden_examples["events"]["device_online"],
        golden_examples["events"]["remote_session_start_requested"],
    ]

    fixtures_path = fixtures_dir / "iot_event_feed_examples_v1.json"
    with open(fixtures_path, "w", encoding="utf-8") as f:
        json.dump(golden_examples, f, indent=2, ensure_ascii=False)
    assert fixtures_path.exists() and fixtures_path.stat().st_size > 0
