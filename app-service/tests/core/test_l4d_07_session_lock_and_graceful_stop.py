from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from core.models.remote_sessions import RemoteSession, RemoteSessionEvent
from core.schemas.remote_sessions import (
    ConsoleCommandCompleteRequest,
    ConsoleCommandStartRequest,
    ConsoleCommandTimeoutRequest,
    RemoteSessionCreate,
    RemoteSessionEventType,
    RemoteSessionLifecycleState,
    RemoteSessionStart,
    RemoteSessionStop,
    RemoteSessionType,
)
from core.services.remote_session_event_service import (
    ConsoleCommandForbiddenError,
    RemoteSessionConflictError,
    RemoteSessionEventService,
    remote_session_event_service,
)
from main import main_app


class SessionLockInMemoryAsyncSession:
    """In-memory async session providing real transaction semantics and unique constraint simulation."""

    def __init__(self) -> None:
        self.sessions: dict[str, RemoteSession] = {}
        self.events: list[RemoteSessionEvent] = []
        self.cursor_seq = 0
        self.committed = False

    def add(self, obj: Any) -> None:
        if isinstance(obj, RemoteSession):
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime.now(UTC)
            # Simulate DB unique index: uq_active_remote_session_per_sn
            active_statuses = {
                RemoteSessionLifecycleState.REQUESTED.value,
                RemoteSessionLifecycleState.STARTING.value,
                RemoteSessionLifecycleState.ACTIVE.value,
                RemoteSessionLifecycleState.STOPPING.value,
            }
            if obj.status in active_statuses:
                for existing in self.sessions.values():
                    if (
                        existing.session_id != obj.session_id
                        and existing.sn == obj.sn
                        and existing.status in active_statuses
                    ):
                        raise sa.exc.IntegrityError(
                            f"UNIQUE constraint failed: tb_remote_sessions.sn on '{obj.sn}'",
                            params={},
                            orig=Exception("uq_active_remote_session_per_sn"),
                        )
            self.sessions[obj.session_id] = obj
        elif isinstance(obj, RemoteSessionEvent):
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime.now(UTC)
            if getattr(obj, "occurred_at", None) is None:
                obj.occurred_at = datetime.now(UTC)
            if obj.cursor is None or obj.cursor <= 0:
                self.cursor_seq += 1
                obj.cursor = self.cursor_seq
            self.events.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        pass

    async def refresh(self, obj: Any) -> None:
        pass

    async def scalar(self, stmt: Any) -> Any:
        where_criteria = getattr(stmt, "_where_criteria", ())
        target_event_id = None
        target_op_id = None
        target_event_type = None
        target_sess_id = None
        target_sn = None

        for criterion in where_criteria:
            if hasattr(criterion, "left") and hasattr(criterion, "right"):
                col_name = getattr(criterion.left, "key", None) or getattr(criterion.left, "name", None)
                val = getattr(criterion.right, "value", None)
                if col_name == "event_id":
                    target_event_id = val
                elif col_name == "operation_id":
                    target_op_id = val
                elif col_name == "event_type":
                    target_event_type = val
                elif col_name == "session_id":
                    target_sess_id = val
                elif col_name == "sn":
                    target_sn = val

        stmt_str = str(stmt).lower()
        if "tb_remote_session_events" in stmt_str or "event" in stmt_str:
            if target_event_id is not None:
                for ev in self.events:
                    if ev.event_id == target_event_id:
                        return ev
            if target_op_id is not None:
                for ev in self.events:
                    if ev.operation_id == target_op_id:
                        if target_event_type is not None:
                            if ev.event_type == target_event_type:
                                return ev
                        else:
                            return ev
                return None

        if "tb_remote_sessions" in stmt_str or "session" in stmt_str:
            if target_op_id is not None:
                for s in self.sessions.values():
                    if s.operation_id == target_op_id:
                        return s
            if target_sess_id is not None:
                if target_sess_id in self.sessions:
                    return self.sessions[target_sess_id]
            if target_sn is not None:
                active_statuses = {
                    RemoteSessionLifecycleState.REQUESTED.value,
                    RemoteSessionLifecycleState.STARTING.value,
                    RemoteSessionLifecycleState.ACTIVE.value,
                    RemoteSessionLifecycleState.STOPPING.value,
                }
                for s in sorted(self.sessions.values(), key=lambda x: x.created_at, reverse=True):
                    if s.sn == target_sn and s.status in active_statuses:
                        return s

        try:
            params = stmt.compile().params
        except Exception:
            params = {}

        for p in params.values():
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

        stmt_str = str(stmt).lower()
        if "tb_remote_sessions" in stmt_str:
            return Result(list(self.sessions.values()))

        params = stmt.compile().params
        after_cursor = 0
        for k, v in params.items():
            if "cursor" in k and isinstance(v, int):
                after_cursor = v
                break

        filtered = [ev for ev in self.events if ev.cursor > after_cursor]
        filtered.sort(key=lambda ev: ev.cursor)
        return Result(filtered)

    async def execute(self, stmt: Any) -> Any:
        class ExecResult:
            def __init__(self, rows: list[Any]) -> None:
                self._rows = rows

            def first(self) -> Any:
                return self._rows[0] if self._rows else None

            def all(self) -> list[Any]:
                return self._rows

        stmt_str = str(stmt).lower()
        if "device" in stmt_str:
            return ExecResult([(1, 10)])
        return ExecResult([(1, 10)])


# ─────────────────────────────────────────────────────────────────────────────
# 1. Simultaneous Starts & Mutual Exclusion Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mutual_exclusion_console_blocks_video_and_video_blocks_console():
    """Verify mutual exclusion: active console blocks video, and active video blocks console on the same SN."""
    session = SessionLockInMemoryAsyncSession()
    service = RemoteSessionEventService()

    # 1. Start console session on SN_MUTUAL_1
    req_console = RemoteSessionCreate(
        operation_id="op-mut-001",
        tenant_id=10,
        terminal_id="term-1",
        sn="SN_MUTUAL_1",
        session_type=RemoteSessionType.CONSOLE,
        auto_start=True,
    )
    console_sess = await service.create_session(session, req_console)
    assert console_sess.status == RemoteSessionLifecycleState.ACTIVE.value
    assert console_sess.session_type == "console"

    # 2. Try starting video session on SN_MUTUAL_1 with different operation_id
    req_video = RemoteSessionCreate(
        operation_id="op-mut-002",
        tenant_id=10,
        terminal_id="term-1",
        sn="SN_MUTUAL_1",
        session_type=RemoteSessionType.VIDEO,
    )
    with pytest.raises(RemoteSessionConflictError) as exc_info:
        await service.create_session(session, req_video)

    conflict = exc_info.value
    assert conflict.code == "session_busy"
    assert conflict.sn == "SN_MUTUAL_1"
    assert conflict.active_session_id == console_sess.session_id
    assert conflict.active_session_type == "console"
    assert conflict.active_status == "active"

    # 3. Now start video session on a different SN (SN_MUTUAL_2)
    req_video_2 = RemoteSessionCreate(
        operation_id="op-mut-003",
        tenant_id=10,
        terminal_id="term-2",
        sn="SN_MUTUAL_2",
        session_type=RemoteSessionType.VIDEO,
        auto_start=True,
    )
    video_sess = await service.create_session(session, req_video_2)
    assert video_sess.status == RemoteSessionLifecycleState.ACTIVE.value

    # 4. Try starting console session on SN_MUTUAL_2 -> blocked by active video session!
    req_console_2 = RemoteSessionCreate(
        operation_id="op-mut-004",
        tenant_id=10,
        terminal_id="term-2",
        sn="SN_MUTUAL_2",
        session_type=RemoteSessionType.CONSOLE,
    )
    with pytest.raises(RemoteSessionConflictError) as exc_info2:
        await service.create_session(session, req_console_2)

    assert exc_info2.value.active_session_id == video_sess.session_id
    assert exc_info2.value.active_session_type == "video"


@pytest.mark.asyncio
async def test_simultaneous_concurrent_starts_mutual_exclusion():
    """Verify that under concurrent simultaneous start requests on the same device, exactly one succeeds."""
    session = SessionLockInMemoryAsyncSession()
    service = RemoteSessionEventService()

    async def attempt_start(op_id: str, s_type: RemoteSessionType) -> tuple[bool, Any]:
        req = RemoteSessionCreate(
            operation_id=op_id,
            tenant_id=10,
            terminal_id="term-sim",
            sn="SN_SIMULTANEOUS",
            session_type=s_type,
            auto_start=True,
        )
        try:
            res = await service.create_session(session, req)
            return True, res
        except (RemoteSessionConflictError, sa.exc.IntegrityError) as err:
            return False, err

    results = await asyncio.gather(
        attempt_start("op-sim-1", RemoteSessionType.CONSOLE),
        attempt_start("op-sim-2", RemoteSessionType.VIDEO),
        attempt_start("op-sim-3", RemoteSessionType.CONSOLE),
    )

    successes = [r for r in results if r[0] is True]
    conflicts = [r for r in results if r[0] is False]

    # Exactly 1 request succeeds; 2 requests receive stable conflict
    assert len(successes) == 1
    assert len(conflicts) == 2


# ─────────────────────────────────────────────────────────────────────────────
# 2. Duplicate Operations & Idempotency Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_operations_idempotency():
    """Verify idempotent creation and stopping with duplicate operation_ids."""
    session = SessionLockInMemoryAsyncSession()
    service = RemoteSessionEventService()

    # 1. Initial creation
    req1 = RemoteSessionCreate(
        operation_id="op-idem-1",
        tenant_id=10,
        terminal_id="term-idem",
        sn="SN_IDEMPOTENT",
        session_type=RemoteSessionType.CONSOLE,
    )
    sess1 = await service.create_session(session, req1)

    # 2. Duplicate call with same operation_id
    req2 = RemoteSessionCreate(
        operation_id="op-idem-1",
        tenant_id=10,
        terminal_id="term-idem",
        sn="SN_IDEMPOTENT",
        session_type=RemoteSessionType.CONSOLE,
    )
    sess2 = await service.create_session(session, req2)
    assert sess1.session_id == sess2.session_id

    # 3. Start session
    started1 = await service.start_session(
        session, sess1.session_id, RemoteSessionStart(operation_id="op-start-1")
    )
    assert started1.status == RemoteSessionLifecycleState.ACTIVE.value

    # 4. Duplicate start_session
    started2 = await service.start_session(
        session, sess1.session_id, RemoteSessionStart(operation_id="op-start-1")
    )
    assert started2.session_id == sess1.session_id
    assert started2.status == RemoteSessionLifecycleState.ACTIVE.value

    # 5. Stop session
    stopped1 = await service.stop_session(
        session, sess1.session_id, RemoteSessionStop(operation_id="op-stop-1", reason="user_stop")
    )
    assert stopped1.status == RemoteSessionLifecycleState.CLOSED.value

    # 6. Duplicate stop_session
    stopped2 = await service.stop_session(
        session, sess1.session_id, RemoteSessionStop(operation_id="op-stop-1", reason="user_stop")
    )
    assert stopped2.session_id == sess1.session_id
    assert stopped2.status == RemoteSessionLifecycleState.CLOSED.value


# ─────────────────────────────────────────────────────────────────────────────
# 3. Crash Recovery & Stale Session Eviction Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crash_recovery_stale_session_eviction():
    """Verify that a stale session without heartbeat is evicted when a new session request arrives."""
    session = SessionLockInMemoryAsyncSession()
    service = RemoteSessionEventService(stale_timeout_sec=5.0)

    # 1. Create and activate Session 1
    req1 = RemoteSessionCreate(
        operation_id="op-crash-1",
        tenant_id=10,
        terminal_id="term-crash",
        sn="SN_CRASH_RECOVER",
        session_type=RemoteSessionType.CONSOLE,
        auto_start=True,
    )
    sess1 = await service.create_session(session, req1)
    assert sess1.status == RemoteSessionLifecycleState.ACTIVE.value

    # 2. Simulate passage of time beyond stale threshold (e.g. 10s past heartbeat)
    sess1.last_heartbeat_at = datetime.now(UTC) - timedelta(seconds=15)

    # 3. Try to create Session 2 on the same SN
    req2 = RemoteSessionCreate(
        operation_id="op-crash-2",
        tenant_id=10,
        terminal_id="term-crash",
        sn="SN_CRASH_RECOVER",
        session_type=RemoteSessionType.VIDEO,
        auto_start=True,
    )
    sess2 = await service.create_session(session, req2)

    # Session 1 was evicted/failed due to stale timeout
    assert sess1.status == RemoteSessionLifecycleState.FAILED.value
    assert sess1.close_reason == "stale_session_timeout"

    # Session 2 took over the device lock successfully
    assert sess2.session_id != sess1.session_id
    assert sess2.status == RemoteSessionLifecycleState.ACTIVE.value
    assert sess2.session_type == "video"


@pytest.mark.asyncio
async def test_cleanup_stale_sessions_sweep():
    """Verify background / periodic sweep cleans up crashed or abandoned sessions."""
    session = SessionLockInMemoryAsyncSession()
    service = RemoteSessionEventService(stale_timeout_sec=10.0)

    req = RemoteSessionCreate(
        operation_id="op-sweep-1",
        tenant_id=10,
        terminal_id="term-sweep",
        sn="SN_SWEEP_01",
        session_type=RemoteSessionType.CONSOLE,
        auto_start=True,
    )
    sess = await service.create_session(session, req)
    sess.last_heartbeat_at = datetime.now(UTC) - timedelta(seconds=20)

    evicted = await service.cleanup_stale_sessions(session, stale_timeout_sec=10.0)
    assert len(evicted) == 1
    assert evicted[0].session_id == sess.session_id
    assert sess.status == RemoteSessionLifecycleState.FAILED.value


# ─────────────────────────────────────────────────────────────────────────────
# 4. Start Failure Lifecycle Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_failure_lifecycle():
    """Verify that when start fails, session transitions to failed, duration is unbilled, and lock is released."""
    session = SessionLockInMemoryAsyncSession()
    service = RemoteSessionEventService()

    # 1. Create session (requested)
    req = RemoteSessionCreate(
        operation_id="op-fail-1",
        tenant_id=10,
        terminal_id="term-fail",
        sn="SN_START_FAIL",
        session_type=RemoteSessionType.CONSOLE,
    )
    sess = await service.create_session(session, req)
    assert sess.status == RemoteSessionLifecycleState.REQUESTED.value
    assert sess.started_at is None

    # 2. Start fails (e.g. device offline)
    failed_sess = await service.mark_session_failed(
        session, sess.session_id, reason="device_offline"
    )
    assert failed_sess.status == RemoteSessionLifecycleState.FAILED.value
    assert failed_sess.close_reason == "device_offline"
    assert failed_sess.started_at is None  # Never became active => billable interval duration is 0!

    # 3. Check event emitted
    ev_failed = [e for e in session.events if e.event_type == RemoteSessionEventType.REMOTE_SESSION_FAILED]
    assert len(ev_failed) == 1
    assert ev_failed[0].lifecycle_state == RemoteSessionLifecycleState.FAILED

    # 4. Lock was released: a new session can now be started on SN_START_FAIL
    req2 = RemoteSessionCreate(
        operation_id="op-fail-2",
        tenant_id=10,
        terminal_id="term-fail",
        sn="SN_START_FAIL",
        session_type=RemoteSessionType.CONSOLE,
        auto_start=True,
    )
    sess2 = await service.create_session(session, req2)
    assert sess2.status == RemoteSessionLifecycleState.ACTIVE.value


# ─────────────────────────────────────────────────────────────────────────────
# 5. Console Command-Aware Graceful Stop Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_console_command_aware_graceful_stop_with_response():
    """Console stop forbids new commands and waits for in-flight command response before closing."""
    session = SessionLockInMemoryAsyncSession()
    service = RemoteSessionEventService()

    # 1. Start console session
    req = RemoteSessionCreate(
        operation_id="op-cmd-stop-1",
        tenant_id=10,
        terminal_id="term-cmd",
        sn="SN_CMD_AWARE_1",
        session_type=RemoteSessionType.CONSOLE,
        auto_start=True,
    )
    sess = await service.create_session(session, req)
    assert sess.status == RemoteSessionLifecycleState.ACTIVE.value

    # 2. Command starts in flight
    ev_start = await service.start_console_command(
        session, session_id=sess.session_id, command_id="sysinfo_cmd"
    )
    assert ev_start.event_type == RemoteSessionEventType.CONSOLE_COMMAND_STARTED
    assert service.get_in_flight_command(sess.session_id) is not None

    # 3. Stop task initiated asynchronously
    stop_task = asyncio.create_task(
        service.stop_session(
            session,
            sess.session_id,
            RemoteSessionStop(operation_id="op-stop-cmd-1", reason="maintenance", timeout_sec=3.0),
        )
    )

    # Let the event loop advance so stop_session marks session stopping
    await asyncio.sleep(0.05)
    assert sess.status == RemoteSessionLifecycleState.STOPPING.value

    # 4. Attempting to start a NEW command while stopping is FORBIDDEN!
    with pytest.raises(ConsoleCommandForbiddenError):
        await service.start_console_command(
            session, session_id=sess.session_id, command_id="forbidden_new_cmd"
        )

    # 5. In-flight command completes cleanly
    ev_comp = await service.complete_console_command(
        session, session_id=sess.session_id, command_id="sysinfo_cmd", exit_code=0
    )
    assert ev_comp.event_type == RemoteSessionEventType.CONSOLE_COMMAND_COMPLETED

    # 6. Stop completes
    stopped_sess = await stop_task
    assert stopped_sess.status == RemoteSessionLifecycleState.CLOSED.value
    assert stopped_sess.close_reason == "maintenance"

    # Verify event ordering: command_started -> stop_requested -> command_completed -> session_closed
    event_types = [e.event_type for e in session.events]
    assert RemoteSessionEventType.CONSOLE_COMMAND_STARTED in event_types
    assert RemoteSessionEventType.REMOTE_SESSION_STOP_REQUESTED in event_types
    assert RemoteSessionEventType.CONSOLE_COMMAND_COMPLETED in event_types
    assert RemoteSessionEventType.REMOTE_SESSION_CLOSED in event_types

    idx_start = event_types.index(RemoteSessionEventType.CONSOLE_COMMAND_STARTED)
    idx_stop_req = event_types.index(RemoteSessionEventType.REMOTE_SESSION_STOP_REQUESTED)
    idx_comp = event_types.index(RemoteSessionEventType.CONSOLE_COMMAND_COMPLETED)
    idx_closed = event_types.index(RemoteSessionEventType.REMOTE_SESSION_CLOSED)
    assert idx_start < idx_stop_req < idx_comp < idx_closed


@pytest.mark.asyncio
async def test_console_command_aware_graceful_stop_with_timeout():
    """Console stop unblocks after timeout if in-flight command does not respond (no infinite wait)."""
    session = SessionLockInMemoryAsyncSession()
    service = RemoteSessionEventService()

    # 1. Start console session
    req = RemoteSessionCreate(
        operation_id="op-cmd-to-1",
        tenant_id=10,
        terminal_id="term-cmd-to",
        sn="SN_CMD_TIMEOUT_1",
        session_type=RemoteSessionType.CONSOLE,
        auto_start=True,
    )
    sess = await service.create_session(session, req)

    # 2. In-flight command starts
    await service.start_console_command(
        session, session_id=sess.session_id, command_id="hanging_process"
    )

    # 3. Stop session with short bounded timeout (0.15s)
    t0 = datetime.now(UTC)
    stopped_sess = await service.stop_session(
        session,
        sess.session_id,
        RemoteSessionStop(operation_id="op-stop-to-1", reason="timeout_stop", timeout_sec=0.15),
    )
    elapsed = (datetime.now(UTC) - t0).total_seconds()

    # Bounded wait respected (not hanging indefinitely)
    assert 0.1 <= elapsed < 1.0
    assert stopped_sess.status == RemoteSessionLifecycleState.CLOSED.value

    # Verify command_timed_out event recorded before session_closed
    event_types = [e.event_type for e in session.events]
    assert RemoteSessionEventType.CONSOLE_COMMAND_TIMED_OUT in event_types
    assert RemoteSessionEventType.REMOTE_SESSION_CLOSED in event_types
    assert event_types.index(RemoteSessionEventType.CONSOLE_COMMAND_TIMED_OUT) < event_types.index(
        RemoteSessionEventType.REMOTE_SESSION_CLOSED
    )


# ─────────────────────────────────────────────────────────────────────────────
# 6. Video Stop Control Flow Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_video_stop_control_flow():
    """Video stop tears down remote/media flow and releases device lock."""
    session = SessionLockInMemoryAsyncSession()
    service = RemoteSessionEventService()

    # Start video session
    req = RemoteSessionCreate(
        operation_id="op-vid-stop-1",
        tenant_id=10,
        terminal_id="term-vid-stop",
        sn="SN_VID_STOP",
        session_type=RemoteSessionType.VIDEO,
        auto_start=True,
    )
    sess = await service.create_session(session, req)
    assert sess.status == RemoteSessionLifecycleState.ACTIVE.value
    assert sess.session_type == "video"

    # Stop video session
    stopped = await service.stop_session(
        session,
        sess.session_id,
        RemoteSessionStop(operation_id="op-vid-stop-req", reason="client_disconnect"),
    )
    assert stopped.status == RemoteSessionLifecycleState.CLOSED.value
    assert stopped.close_reason == "client_disconnect"

    # Events emitted: stop_requested -> closed
    ev_types = [e.event_type for e in session.events]
    assert RemoteSessionEventType.REMOTE_SESSION_STOP_REQUESTED in ev_types
    assert RemoteSessionEventType.REMOTE_SESSION_CLOSED in ev_types

    # Lock is released: new console session can now start
    req_console = RemoteSessionCreate(
        operation_id="op-vid-stop-follow",
        tenant_id=10,
        terminal_id="term-vid-stop",
        sn="SN_VID_STOP",
        session_type=RemoteSessionType.CONSOLE,
        auto_start=True,
    )
    new_sess = await service.create_session(session, req_console)
    assert new_sess.status == RemoteSessionLifecycleState.ACTIVE.value


@pytest.mark.asyncio
async def test_stop_uses_row_lock_and_replay_does_not_repeat_teardown(monkeypatch):
    """A lost HTTP response can be retried without repeating resource teardown or events."""

    class LockTrackingSession(SessionLockInMemoryAsyncSession):
        def __init__(self) -> None:
            super().__init__()
            self.for_update_queries = 0

        async def scalar(self, stmt: Any) -> Any:
            if getattr(stmt, "_for_update_arg", None) is not None:
                self.for_update_queries += 1
            return await super().scalar(stmt)

    session = LockTrackingSession()
    service = RemoteSessionEventService()
    created = await service.create_session(
        session,
        RemoteSessionCreate(
            operation_id="op-stop-lock-create",
            tenant_id=10,
            terminal_id="term-stop-lock",
            sn="SN_STOP_LOCK",
            session_type=RemoteSessionType.VIDEO,
            auto_start=True,
        ),
    )
    teardown_calls = 0

    async def track_teardown(rec: RemoteSession, reason: str = "stop") -> None:
        nonlocal teardown_calls
        teardown_calls += 1

    monkeypatch.setattr(service, "_teardown_video_session", track_teardown)
    stop = RemoteSessionStop(
        operation_id="op-stop-lock",
        reason="user_requested",
        tenant_id=10,
        sn="SN_STOP_LOCK",
    )

    first = await service.stop_session(session, created.session_id, stop)
    replay = await service.stop_session(session, created.session_id, stop)

    assert first is replay
    assert replay.status == RemoteSessionLifecycleState.CLOSED.value
    assert session.for_update_queries == 2
    assert teardown_calls == 1
    assert [event.event_type for event in session.events].count(
        RemoteSessionEventType.REMOTE_SESSION_STOP_REQUESTED
    ) == 1
    assert [event.event_type for event in session.events].count(
        RemoteSessionEventType.REMOTE_SESSION_CLOSED
    ) == 1


@pytest.mark.asyncio
async def test_stop_rejects_tenant_or_sn_identity_mismatch():
    """A stale consumer cannot stop a session through another tenant or terminal identity."""
    session = SessionLockInMemoryAsyncSession()
    service = RemoteSessionEventService()
    created = await service.create_session(
        session,
        RemoteSessionCreate(
            operation_id="op-stop-identity-create",
            tenant_id=10,
            terminal_id="term-stop-identity",
            sn="SN_STOP_IDENTITY",
            session_type=RemoteSessionType.VIDEO,
            auto_start=True,
        ),
    )

    for stop in (
        RemoteSessionStop(operation_id="op-wrong-tenant", tenant_id=11, sn="SN_STOP_IDENTITY"),
        RemoteSessionStop(operation_id="op-wrong-sn", tenant_id=10, sn="SN_OTHER"),
    ):
        with pytest.raises(Exception) as exc_info:
            await service.stop_session(session, created.session_id, stop)
        assert getattr(exc_info.value, "code", None) == "session_identity_mismatch"

    assert created.status == RemoteSessionLifecycleState.ACTIVE.value
    assert RemoteSessionEventType.REMOTE_SESSION_STOP_REQUESTED not in {
        event.event_type for event in session.events
    }


@pytest.mark.asyncio
async def test_stop_teardown_failure_is_durable_and_retryable(monkeypatch):
    """A resource teardown error must not be reported as closed and can be resumed after restart."""
    session = SessionLockInMemoryAsyncSession()
    first_service = RemoteSessionEventService()
    created = await first_service.create_session(
        session,
        RemoteSessionCreate(
            operation_id="op-stop-retry-create",
            tenant_id=10,
            terminal_id="term-stop-retry",
            sn="SN_STOP_RETRY",
            session_type=RemoteSessionType.VIDEO,
            auto_start=True,
        ),
    )

    async def fail_teardown(rec: RemoteSession, reason: str = "stop") -> None:
        raise RuntimeError("lease registry unavailable")

    monkeypatch.setattr(first_service, "_teardown_video_session", fail_teardown)
    stop = RemoteSessionStop(
        operation_id="op-stop-retry",
        reason="user_requested",
        tenant_id=10,
        sn="SN_STOP_RETRY",
    )

    with pytest.raises(Exception) as exc_info:
        await first_service.stop_session(session, created.session_id, stop)

    assert getattr(exc_info.value, "code", None) == "stop_teardown_failed"
    assert created.status == RemoteSessionLifecycleState.STOPPING.value
    assert session.committed is True
    assert RemoteSessionEventType.REMOTE_SESSION_CLOSED not in {
        event.event_type for event in session.events
    }

    restarted_service = RemoteSessionEventService()

    async def successful_teardown(rec: RemoteSession, reason: str = "stop") -> None:
        return None

    monkeypatch.setattr(restarted_service, "_teardown_video_session", successful_teardown)
    stopped = await restarted_service.stop_session(session, created.session_id, stop)

    assert stopped is created
    assert stopped.status == RemoteSessionLifecycleState.CLOSED.value
    assert [event.event_type for event in session.events].count(
        RemoteSessionEventType.REMOTE_SESSION_STOP_REQUESTED
    ) == 1
    assert [event.event_type for event in session.events].count(
        RemoteSessionEventType.REMOTE_SESSION_CLOSED
    ) == 1


@pytest.mark.asyncio
async def test_late_stop_for_closed_session_does_not_touch_new_session(monkeypatch):
    """A delayed stop by old session ID cannot close or tear down its successor."""
    session = SessionLockInMemoryAsyncSession()
    service = RemoteSessionEventService()
    old_session = await service.create_session(
        session,
        RemoteSessionCreate(
            operation_id="op-old-create",
            tenant_id=10,
            terminal_id="term-late-stop",
            sn="SN_LATE_STOP",
            session_type=RemoteSessionType.VIDEO,
            auto_start=True,
        ),
    )
    await service.stop_session(
        session,
        old_session.session_id,
        RemoteSessionStop(operation_id="op-old-stop", tenant_id=10, sn="SN_LATE_STOP"),
    )
    new_session = await service.create_session(
        session,
        RemoteSessionCreate(
            operation_id="op-new-create",
            tenant_id=10,
            terminal_id="term-late-stop",
            sn="SN_LATE_STOP",
            session_type=RemoteSessionType.VIDEO,
            auto_start=True,
        ),
    )

    async def unexpected_teardown(rec: RemoteSession, reason: str = "stop") -> None:
        raise AssertionError("late stop attempted resource teardown")

    monkeypatch.setattr(service, "_teardown_video_session", unexpected_teardown)
    replay = await service.stop_session(
        session,
        old_session.session_id,
        RemoteSessionStop(operation_id="op-late-stop", tenant_id=10, sn="SN_LATE_STOP"),
    )

    assert replay is old_session
    assert replay.status == RemoteSessionLifecycleState.CLOSED.value
    assert new_session.status == RemoteSessionLifecycleState.ACTIVE.value


# ─────────────────────────────────────────────────────────────────────────────
# 7. Lifecycle Transitions, Event Ordering & Billable Interval Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lifecycle_transitions_ordering_and_billable_interval():
    """Full lifecycle: requested -> starting -> active -> stopping -> closed with billable interval check."""
    session = SessionLockInMemoryAsyncSession()
    service = RemoteSessionEventService()

    # Step 1: Requested
    req = RemoteSessionCreate(
        operation_id="op-life-1",
        tenant_id=10,
        terminal_id="term-life",
        sn="SN_LIFECYCLE",
        session_type=RemoteSessionType.CONSOLE,
    )
    sess = await service.create_session(session, req)
    assert sess.status == RemoteSessionLifecycleState.REQUESTED.value
    assert sess.started_at is None
    assert sess.closed_at is None

    # Step 2: Starting
    await service.mark_session_starting(session, sess.session_id)
    assert sess.status == RemoteSessionLifecycleState.STARTING.value
    assert sess.started_at is None

    # Step 3: Active
    await service.mark_session_active(session, sess.session_id)
    assert sess.status == RemoteSessionLifecycleState.ACTIVE.value
    assert sess.started_at is not None
    assert sess.closed_at is None

    # Step 4 & 5: Stopping -> Closed via stop_session
    await service.stop_session(
        session, sess.session_id, RemoteSessionStop(reason="normal_exit")
    )
    assert sess.status == RemoteSessionLifecycleState.CLOSED.value
    assert sess.closed_at is not None

    # Billable duration strictly from started_at to closed_at:
    duration_sec = (sess.closed_at - sess.started_at).total_seconds()
    assert duration_sec >= 0.0

    # Event ordering verification
    events = session.events
    assert len(events) == 5
    cursors = [e.cursor for e in events]
    assert cursors == sorted(cursors)
    assert len(set(cursors)) == len(cursors)  # Strictly monotonic

    expected_types = [
        RemoteSessionEventType.REMOTE_SESSION_START_REQUESTED,
        RemoteSessionEventType.REMOTE_SESSION_STARTING,
        RemoteSessionEventType.REMOTE_SESSION_ACTIVE,
        RemoteSessionEventType.REMOTE_SESSION_STOP_REQUESTED,
        RemoteSessionEventType.REMOTE_SESSION_CLOSED,
    ]
    actual_types = [e.event_type for e in events]
    assert actual_types == expected_types

    expected_states = [
        RemoteSessionLifecycleState.REQUESTED,
        RemoteSessionLifecycleState.STARTING,
        RemoteSessionLifecycleState.ACTIVE,
        RemoteSessionLifecycleState.STOPPING,
        RemoteSessionLifecycleState.CLOSED,
    ]
    actual_states = [e.lifecycle_state for e in events]
    assert actual_states == expected_states


# ─────────────────────────────────────────────────────────────────────────────
# 8. REST API Endpoints Integration Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rest_api_session_lock_mutual_exclusion_and_endpoints(monkeypatch):
    """Verify REST API behavior for create, start, heartbeat, stop, command tracking, and conflict 409."""
    shared_session = SessionLockInMemoryAsyncSession()

    from api.internal_v1 import internal_depends
    from core.models.db_helper import db_helper

    class FakeAsyncSessionCtx:
        async def __aenter__(self):
            return shared_session

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr(db_helper, "session_factory", lambda: FakeAsyncSessionCtx())

    async def override_session():
        yield shared_session

    async def override_auth():
        return {"sub": "internal_test", "role": "admin"}

    main_app.dependency_overrides[db_helper.session_getter] = override_session
    main_app.dependency_overrides[internal_depends.verify_internal_service_auth] = override_auth

    transport = ASGITransport(app=main_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        headers = {"Authorization": "Bearer internal-secret"}

        # 1. Create console session
        resp1 = await client.post(
            "/api/internal/v1/remote-sessions",
            headers=headers,
            json={
                "operation_id": "api-op-001",
                "contract_version": "1.0.0",
                "tenant_id": 1,
                "terminal_id": "term-api",
                "sn": "SN_API_LOCK_1",
                "session_type": "console",
                "auto_start": True,
            },
        )
        assert resp1.status_code == 201
        data1 = resp1.json()
        assert data1["status"] == "active"
        session_id_1 = data1["session_id"]

        # 2. Try creating another session for same SN -> returns 409 Conflict
        resp2 = await client.post(
            "/api/internal/v1/remote-sessions",
            headers=headers,
            json={
                "operation_id": "api-op-002",
                "contract_version": "1.0.0",
                "tenant_id": 1,
                "terminal_id": "term-api",
                "sn": "SN_API_LOCK_1",
                "session_type": "video",
            },
        )
        assert resp2.status_code == 409
        err = resp2.json()["detail"]
        assert err["code"] == "session_busy"
        assert err["sn"] == "SN_API_LOCK_1"
        assert err["active_session_id"] == session_id_1

        # 3. Duplicate create on operation_id -> returns 201 idempotently
        resp_dup = await client.post(
            "/api/internal/v1/remote-sessions",
            headers=headers,
            json={
                "operation_id": "api-op-001",
                "contract_version": "1.0.0",
                "tenant_id": 1,
                "terminal_id": "term-api",
                "sn": "SN_API_LOCK_1",
                "session_type": "console",
            },
        )
        assert resp_dup.status_code == 201
        assert resp_dup.json()["session_id"] == session_id_1

        # 4. Heartbeat
        resp_hb = await client.post(
            f"/api/internal/v1/remote-sessions/{session_id_1}/heartbeat",
            headers=headers,
        )
        assert resp_hb.status_code == 200
        assert resp_hb.json()["last_heartbeat_at"] is not None

        # 5. Start console command
        resp_cmd = await client.post(
            f"/api/internal/v1/remote-sessions/{session_id_1}/commands/start",
            headers=headers,
            json={"command_id": "cmd_api_test"},
        )
        assert resp_cmd.status_code == 200
        assert resp_cmd.json()["status"] == "started"

        # 6. Complete console command
        resp_comp = await client.post(
            f"/api/internal/v1/remote-sessions/{session_id_1}/commands/complete",
            headers=headers,
            json={"command_id": "cmd_api_test", "exit_code": 0},
        )
        assert resp_comp.status_code == 200
        assert resp_comp.json()["status"] == "completed"

        # 7. A stale tenant/SN identity cannot stop this session
        resp_mismatch = await client.post(
            f"/api/internal/v1/remote-sessions/{session_id_1}/stop",
            headers=headers,
            json={
                "operation_id": "api-stop-wrong-identity",
                "tenant_id": 2,
                "sn": "SN_API_LOCK_1",
                "reason": "api_test_done",
            },
        )
        assert resp_mismatch.status_code == 409
        mismatch_detail = resp_mismatch.json()["detail"]
        assert mismatch_detail["code"] == "session_identity_mismatch"
        assert mismatch_detail["actual_tenant_id"] == 1
        assert shared_session.sessions[session_id_1].status == "active"

        # 8. Stop session
        resp_stop = await client.post(
            f"/api/internal/v1/remote-sessions/{session_id_1}/stop",
            headers=headers,
            json={
                "operation_id": "api-stop-001",
                "tenant_id": 1,
                "sn": "SN_API_LOCK_1",
                "reason": "api_test_done",
            },
        )
        assert resp_stop.status_code == 200
        assert resp_stop.json()["status"] == "closed"

        # 9. After stop, lock is freed -> creating new session succeeds!
        resp3 = await client.post(
            "/api/internal/v1/remote-sessions",
            headers=headers,
            json={
                "operation_id": "api-op-003",
                "contract_version": "1.0.0",
                "tenant_id": 1,
                "terminal_id": "term-api",
                "sn": "SN_API_LOCK_1",
                "session_type": "video",
                "auto_start": True,
            },
        )
        assert resp3.status_code == 201
        assert resp3.json()["session_type"] == "video"
        session_id_2 = resp3.json()["session_id"]

        # 10. Teardown failure is explicit and retryable; it never reports false closed
        async def fail_video_teardown(rec: RemoteSession, reason: str = "stop") -> None:
            raise RuntimeError("lease registry unavailable")

        monkeypatch.setattr(
            remote_session_event_service,
            "_teardown_video_session",
            fail_video_teardown,
        )
        resp_failed_stop = await client.post(
            f"/api/internal/v1/remote-sessions/{session_id_2}/stop",
            headers=headers,
            json={
                "operation_id": "api-stop-002",
                "tenant_id": 1,
                "sn": "SN_API_LOCK_1",
                "reason": "api_test_done",
            },
        )
        assert resp_failed_stop.status_code == 503
        failed_detail = resp_failed_stop.json()["detail"]
        assert failed_detail == {
            "code": "stop_teardown_failed",
            "message": f"Resource teardown failed for remote session '{session_id_2}'",
            "session_id": session_id_2,
            "status": "stopping",
            "retryable": True,
        }

        async def successful_video_teardown(rec: RemoteSession, reason: str = "stop") -> None:
            return None

        monkeypatch.setattr(
            remote_session_event_service,
            "_teardown_video_session",
            successful_video_teardown,
        )
        resp_retry = await client.post(
            f"/api/internal/v1/remote-sessions/{session_id_2}/stop",
            headers=headers,
            json={
                "operation_id": "api-stop-002",
                "tenant_id": 1,
                "sn": "SN_API_LOCK_1",
                "reason": "api_test_done",
            },
        )
        assert resp_retry.status_code == 200
        assert resp_retry.json()["status"] == "closed"

    main_app.dependency_overrides.clear()
