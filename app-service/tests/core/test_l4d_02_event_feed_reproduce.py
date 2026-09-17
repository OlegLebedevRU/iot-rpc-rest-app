from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from unittest.mock import AsyncMock

from core.config import settings
from core.diagnostics.sessions import DiagnosticsSessionRegistry, DiagnosticSession, DiagnosticSessionKind
from core.models.base import Base
from core.models import db_helper
from core.schemas.remote_sessions import RemoteSessionEventFeedResponse
from core.services.remote_session_event_service import remote_session_event_service
from main import main_app
from datetime import UTC, datetime


@pytest.mark.asyncio
async def test_reproduce_event_feed_tables_metadata():
    """Verify that durable session events and sessions tables are defined with required columns and constraints."""
    assert "tb_remote_session_events" in Base.metadata.tables, (
        "tb_remote_session_events table must be registered in Base.metadata"
    )
    assert "tb_remote_sessions" in Base.metadata.tables, (
        "tb_remote_sessions table must be registered in Base.metadata"
    )

    events_table = Base.metadata.tables["tb_remote_session_events"]
    expected_event_cols = {
        "cursor",
        "event_id",
        "occurred_at",
        "tenant_id",
        "terminal_id",
        "device_id",
        "sn",
        "session_id",
        "session_type",
        "event_type",
        "event_version",
        "lifecycle_state",
        "reason",
        "operation_id",
        "correlation_id",
        "payload",
        "created_at",
    }
    assert expected_event_cols.issubset(set(events_table.columns.keys()))

    sessions_table = Base.metadata.tables["tb_remote_sessions"]
    expected_sess_cols = {
        "id",
        "session_id",
        "tenant_id",
        "terminal_id",
        "device_id",
        "sn",
        "session_type",
        "status",
        "requested_by_user_id",
        "operation_id",
        "correlation_id",
        "created_at",
        "started_at",
        "closed_at",
        "last_heartbeat_at",
        "close_reason",
        "session_metadata",
    }
    assert expected_sess_cols.issubset(set(sessions_table.columns.keys()))


@pytest.mark.asyncio
async def test_event_feed_endpoints_presence_and_auth_protection(monkeypatch):
    """Verify that event feed and remote session endpoints are present and properly protected by auth."""
    fake_session = AsyncMock()
    fake_feed = RemoteSessionEventFeedResponse(
        items=[],
        next_cursor=0,
        has_more=False,
        total_count=0,
        server_time=datetime.now(UTC),
    )

    async def fake_session_getter():
        yield fake_session

    main_app.dependency_overrides[db_helper.session_getter] = fake_session_getter
    monkeypatch.setattr(remote_session_event_service, "get_event_feed", AsyncMock(return_value=fake_feed))

    try:
        transport = ASGITransport(app=main_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Unauthenticated request must return 403 Forbidden
            resp_unauth = await client.get("/api/internal/v1/remote-session-events")
            assert resp_unauth.status_code == 403, f"Expected 403 Forbidden, got {resp_unauth.status_code}"

            # 2. Authenticated request with valid api key must succeed (200 OK)
            auth_headers = {
                "X-Internal-Service-Key": "test",
                "X-Org-Id": "1",
                "X-Role": "superuser",
            }
            resp_auth = await client.get("/api/internal/v1/remote-session-events", headers=auth_headers)
            assert resp_auth.status_code == 200, f"Expected 200 OK, got {resp_auth.status_code}"
            feed_data = resp_auth.json()
            assert "items" in feed_data
            assert "next_cursor" in feed_data
            assert "has_more" in feed_data
    finally:
        main_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_reproduce_in_memory_facts_loss_on_restart():
    """Demonstrate that in-memory registries lose session history and emit no durable event feed."""
    temp_registry = DiagnosticsSessionRegistry()
    session = DiagnosticSession(
        sn="SNTEST01",
        session_id="sess-001",
        kind=DiagnosticSessionKind.EXEC,
        ttl_sec=60,
        command_id="system_info",
    )
    await temp_registry.register(session)
    active = await temp_registry.list_active()
    assert len(active) == 1

    # Simulate restart by clearing in-memory state
    new_registry = DiagnosticsSessionRegistry()
    active_after_restart = await new_registry.list_active()
    assert len(active_after_restart) == 0, "In-memory session registry has no persistence"
    # Notice: No event feed was generated, no cursor, no audit trail survived.
