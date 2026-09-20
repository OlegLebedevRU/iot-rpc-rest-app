from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import tempfile
from typing import Any
import uuid

import pytest

from core.archive import (
    ActiveRecordsDetectedError,
    ChecksumMismatchError,
    CursorGuard,
    CursorLagDetectedError,
    DiskSpaceExhaustedError,
    HotRetentionViolationError,
    PathSecurityGuard,
    RestoreSampleFailedError,
    RetentionGuard,
    VolumeUnavailableError,
    get_manifest_schema,
    run_archive_cycle,
    scrub_secrets,
    serialize_record_envelope,
    validate_manifest_data,
    write_deterministic_jsonl_gz,
)
from core.models.archive import FinArchiveBatch
from core.models.device_events import DevEvent
from core.models.device_tasks import DevTask
from core.models.remote_sessions import RemoteSession, RemoteSessionEvent


# -------------------------------------------------------------------------
# Test InMemory AsyncSession for full DB cycle simulation
# -------------------------------------------------------------------------
class ArchiveMockAsyncSession:
    """Mock AsyncSession simulating transactions, filtering, and bounded deletions for tests."""

    def __init__(self) -> None:
        self.remote_sessions: dict[str, RemoteSession] = {}
        self.remote_events: list[RemoteSessionEvent] = []
        self.dev_tasks: list[DevTask] = []
        self.dev_events: list[DevEvent] = []
        self.archive_batches: dict[tuple[str, str], FinArchiveBatch] = {}
        self.cursor_seq = 10000

    def add(self, obj: Any) -> None:
        if isinstance(obj, RemoteSession):
            self.remote_sessions[obj.session_id] = obj
        elif isinstance(obj, RemoteSessionEvent):
            if obj.cursor is None or obj.cursor <= 0:
                self.cursor_seq += 1
                obj.cursor = self.cursor_seq
            self.remote_events.append(obj)
        elif isinstance(obj, DevTask):
            self.dev_tasks.append(obj)
        elif isinstance(obj, DevEvent):
            self.dev_events.append(obj)
        elif isinstance(obj, FinArchiveBatch):
            self.archive_batches[(obj.id, obj.source_project)] = obj

    async def get(self, model: Any, ident: Any) -> Any:
        if model is FinArchiveBatch:
            if isinstance(ident, tuple):
                return self.archive_batches.get(ident)
            return None
        return None

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def execute(self, stmt: Any) -> Any:
        stmt_str = str(stmt).lower()

        # Handle FinArchiveBatch select
        if "fin_archive_batches" in stmt_str and "select" in stmt_str:
            batches = list(self.archive_batches.values())
            return MockResult(scalars_list=batches)

        # Handle RemoteSession count (ActiveRecordsGuard)
        if "tb_remote_sessions" in stmt_str and "count" in stmt_str:
            # Check for active sessions
            active_count = 0
            for s in self.remote_sessions.values():
                if s.status in ("requested", "starting", "active", "stopping"):
                    active_count += 1
            return MockScalarResult(active_count)

        selected_col = None
        if hasattr(stmt, "column_descriptions") and stmt.column_descriptions:
            selected_col = stmt.column_descriptions[0].get("name")

        # Handle RemoteSessionEvent select
        if "tb_remote_session_events" in stmt_str and "select" in stmt_str:
            if selected_col == "event_id":
                return MockResult(scalars_list=[e.event_id for e in self.remote_events])
            return MockResult(scalars_list=list(self.remote_events))

        # Handle DevTask select
        if "tb_dev_tasks" in stmt_str and "select" in stmt_str:
            if selected_col == "id":
                return MockResult(scalars_list=[t.id for t in self.dev_tasks])
            return MockResult(scalars_list=list(self.dev_tasks))

        # Handle DevEvent select
        if "tb_dev_events" in stmt_str and "select" in stmt_str:
            if selected_col == "id":
                return MockResult(scalars_list=[e.id for e in self.dev_events])
            return MockResult(scalars_list=list(self.dev_events))

        # Handle Purge DELETE RemoteSessionEvent
        if "tb_remote_session_events" in stmt_str and "delete" in stmt_str:
            deleted_count = len(self.remote_events)
            self.remote_events.clear()
            return MockDeleteResult(deleted_count)

        # Handle Purge DELETE DevTask
        if "tb_dev_tasks" in stmt_str and "delete" in stmt_str:
            deleted_count = len(self.dev_tasks)
            self.dev_tasks.clear()
            return MockDeleteResult(deleted_count)

        # Handle Purge DELETE DevEvent
        if "tb_dev_events" in stmt_str and "delete" in stmt_str:
            deleted_count = len(self.dev_events)
            self.dev_events.clear()
            return MockDeleteResult(deleted_count)

        return MockResult(scalars_list=[])


class MockResult:
    def __init__(self, scalars_list: list[Any]) -> None:
        self._items = scalars_list

    def scalars(self) -> Any:
        return self

    def all(self) -> list[Any]:
        return self._items

    def first(self) -> Any | None:
        return self._items[0] if self._items else None


class MockScalarResult:
    def __init__(self, val: Any) -> None:
        self._val = val

    def scalar(self) -> Any:
        return self._val


class MockDeleteResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


# -------------------------------------------------------------------------
# Test 1: Contract digests and canonical schemas conformance
# -------------------------------------------------------------------------
def test_contract_digests_and_schema_validation():
    """Verify that JSON Schema is valid Draft 2020-12 and canonical golden example validates."""
    schema = get_manifest_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == "L4Desk Archive Manifest Contract 1.0.0"

    # Golden example test
    golden_example_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "l4desk-service"
        / "docs"
        / "prompts"
        / "contracts"
        / "archive-manifest-v1"
        / "examples.json"
    )
    assert golden_example_path.is_file()
    with open(golden_example_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Validate each valid example against schema
    for case in data.get("cases", []):
        if case.get("valid") is True and case.get("schema") == "ArchiveManifest":
            validate_manifest_data(case["body"])


# -------------------------------------------------------------------------
# Test 2: Deterministic serialization and secret scrubbing
# -------------------------------------------------------------------------
def test_deterministic_serialization_and_secret_scrubbing():
    """Verify deterministic JSON serialization, secret scrubbing, and byte-reproducible gzip."""
    raw_payload = {
        "device_token": "secret-12345",
        "api_key": "raw-key-abc",
        "nested": {"password": "pass", "normal_field": "ok"},
        "pin_code": 9999,
        "auth_header": "Bearer xyz",
        "command": "reboot",
    }
    scrubbed = scrub_secrets(raw_payload)
    assert scrubbed["device_token"] == "[SCRUBBED]"
    assert scrubbed["api_key"] == "[SCRUBBED]"
    assert scrubbed["nested"]["password"] == "[SCRUBBED]"
    assert scrubbed["nested"]["normal_field"] == "ok"
    assert scrubbed["pin_code"] == "[SCRUBBED]"
    assert scrubbed["auth_header"] == "[SCRUBBED]"
    assert scrubbed["command"] == "reboot"

    record = {
        "record_type": "iot_session_events",
        "record_id": "evt-001",
        "occurred_at_utc": "2026-05-15T10:00:00Z",
        "cursor": 10001,
        "tenant_id": 1,
        "terminal_id": 10,
        "sn": "SN-001",
        "session_id": "sess-001",
        "source_project": "iot-rpc-rest-app",
        "payload": scrubbed,
    }

    serialized1 = serialize_record_envelope(record)
    serialized2 = serialize_record_envelope(record)
    assert serialized1 == serialized2
    assert serialized1.endswith("\n")

    # Verify gzip deterministic byte output (mtime=0.0)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path1 = Path(tmp_dir) / "data1.jsonl.gz"
        tmp_path2 = Path(tmp_dir) / "data2.jsonl.gz"

        c1, size1, h1 = write_deterministic_jsonl_gz([record], tmp_path1)
        c2, size2, h2 = write_deterministic_jsonl_gz([record], tmp_path2)

        assert c1 == c2 == 1
        assert size1 == size2
        assert h1 == h2
        assert tmp_path1.read_bytes() == tmp_path2.read_bytes()


# -------------------------------------------------------------------------
# Test 3: Retention boundaries guard
# -------------------------------------------------------------------------
def test_retention_boundary_guard():
    """Verify strictly older than 3 full closed calendar months invariant."""
    simulated_now = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)

    # In September (month 9), months 8, 7, 6 are within 3 closed months window.
    # Month 5 (May 2026) is the first allowed closed month (diff = 9 - 5 = 4 >= 4).
    min_dt, max_dt = RetentionGuard.parse_and_validate_source_month(
        "2026-05", simulated_now
    )
    assert min_dt == datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)
    assert max_dt == datetime(2026, 5, 31, 23, 59, 59, 999999, tzinfo=UTC)

    # Older months allowed
    min_dt_apr, max_dt_apr = RetentionGuard.parse_and_validate_source_month(
        "2026-04", simulated_now
    )
    assert min_dt_apr.month == 4

    # Hot retention violations (months 6, 7, 8, 9)
    for hot_month in ("2026-06", "2026-07", "2026-08", "2026-09"):
        with pytest.raises(HotRetentionViolationError):
            RetentionGuard.parse_and_validate_source_month(hot_month, simulated_now)

    # Invalid formats
    with pytest.raises(ValueError):
        RetentionGuard.parse_and_validate_source_month("2026/05", simulated_now)
    with pytest.raises(ValueError):
        RetentionGuard.parse_and_validate_source_month("invalid", simulated_now)


# -------------------------------------------------------------------------
# Test 4: Cursor guard and lag detection
# -------------------------------------------------------------------------
def test_cursor_guard():
    """Verify CursorGuard enforces consumers_passed_cursor >= through_cursor."""
    # When through_cursor is None or 0, any cursor passes
    CursorGuard.verify_cursor_bounds(None, None)
    CursorGuard.verify_cursor_bounds(0, 0)

    # Normal passing cases
    CursorGuard.verify_cursor_bounds(
        through_cursor=25000, consumers_passed_cursor=25000
    )
    CursorGuard.verify_cursor_bounds(
        through_cursor=25000, consumers_passed_cursor=26500
    )

    # Cursor lag cases
    with pytest.raises(CursorLagDetectedError):
        CursorGuard.verify_cursor_bounds(
            through_cursor=25000, consumers_passed_cursor=24999
        )

    with pytest.raises(CursorLagDetectedError):
        CursorGuard.verify_cursor_bounds(
            through_cursor=25000, consumers_passed_cursor=None
        )


# -------------------------------------------------------------------------
# Test 5: Path security and traversal protection
# -------------------------------------------------------------------------
def test_path_security_guard():
    """Verify PathSecurityGuard blocks directory traversal and symlink vulnerabilities."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir).resolve()

        # Valid subpaths
        sub = PathSecurityGuard.validate_and_resolve_path(
            root, "2026/05/iot-rpc-rest-app/batch-1"
        )
        assert sub.is_relative_to(root)

        # Path traversal with ..
        with pytest.raises(VolumeUnavailableError):
            PathSecurityGuard.validate_and_resolve_path(root, "../outside")

        # Null bytes
        with pytest.raises(VolumeUnavailableError):
            PathSecurityGuard.validate_and_resolve_path(root, "sub\0dir")

        # Disk space check
        PathSecurityGuard.check_disk_space(root, min_free_bytes=1024)

        with pytest.raises(DiskSpaceExhaustedError):
            # Check with impossibly huge disk requirement (10 Petabytes)
            PathSecurityGuard.check_disk_space(
                root, min_free_bytes=10 * 1024 * 1024 * 1024 * 1024 * 1024
            )


# -------------------------------------------------------------------------
# Test 6: Active records guard
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_active_records_guard():
    """Verify ActiveRecordsGuard detects active, unclosed, or reopened sessions."""
    from core.archive.guards import ActiveRecordsGuard

    session = ArchiveMockAsyncSession()
    min_dt = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)
    max_dt = datetime(2026, 5, 31, 23, 59, 59, tzinfo=UTC)

    # When all sessions are closed
    closed_sess = RemoteSession(
        session_id="sess-closed-1",
        sn="SN-01",
        session_type="console",
        status="closed",
        created_at=min_dt + timedelta(days=2),
        closed_at=min_dt + timedelta(days=2, hours=1),
    )
    session.add(closed_sess)
    await ActiveRecordsGuard.verify_no_active_records(session, min_dt, max_dt)

    # When an active session exists
    active_sess = RemoteSession(
        session_id="sess-active-1",
        sn="SN-02",
        session_type="console",
        status="active",
        created_at=min_dt + timedelta(days=5),
        closed_at=None,
    )
    session.add(active_sess)
    with pytest.raises(ActiveRecordsDetectedError):
        await ActiveRecordsGuard.verify_no_active_records(session, min_dt, max_dt)


# -------------------------------------------------------------------------
# Test 7: Full archive lifecycle & No-Financial-Purge verification
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_full_archive_lifecycle_and_no_financial_purge():
    """Verify end-to-end export, verification, atomic promotion, and bounded purge."""
    session = ArchiveMockAsyncSession()
    simulated_now = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)

    # 1. Populate closed session summary (tb_remote_sessions) -> MUST NEVER BE PURGED
    session_summary = RemoteSession(
        session_id="sess-2026-05-1",
        sn="PAX-001",
        session_type="console",
        status="closed",
        created_at=datetime(2026, 5, 10, 10, 0, 0, tzinfo=UTC),
        closed_at=datetime(2026, 5, 10, 10, 30, 0, tzinfo=UTC),
    )
    session.add(session_summary)

    # 2. Populate high-volume details for 2026-05
    for i in range(1, 11):
        ev = RemoteSessionEvent(
            event_id=f"evt-{i}",
            cursor=10000 + i,
            occurred_at=datetime(2026, 5, 10, 10, i, 0, tzinfo=UTC),
            tenant_id=42,
            terminal_id="101",
            sn="PAX-001",
            session_id="sess-2026-05-1",
            payload={"action": f"step-{i}", "token": "secret-to-scrub"},
        )
        session.add(ev)

    # Add a device task
    task = DevTask(
        id=uuid.uuid4(),
        device_id=101,
        method_code=100,
        created_at=datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC),
        deleted_at=datetime(2026, 5, 11, 12, 1, 0, tzinfo=UTC),
    )
    session.add(task)

    # Add a device event
    dev_ev = DevEvent(
        id=701,
        device_id=101,
        event_type_code=1,  # online
        created_at=datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC),
        payload={"ip": "10.0.0.1"},
    )
    session.add(dev_ev)

    with tempfile.TemporaryDirectory() as tmp_volume:
        vol_root = Path(tmp_volume).resolve()

        # Execute archive cycle with cursor >= max_cursor (10010)
        manifest, batch_db = await run_archive_cycle(
            session=session,
            volume_root=vol_root,
            source_month="2026-05",
            consumers_passed_cursor=10015,
            dry_run=False,
            purge=True,
            now_utc=simulated_now,
            seed="test-seed-1",
        )

        assert batch_db.state == "purged"
        assert manifest["state"] == "purged"
        assert manifest["archive_batch_id"].startswith("arch-iot-2026-05-")
        assert (
            manifest["record_counts"]["total_records"] == 12
        )  # 10 evs + 1 task + 1 dev_ev
        assert manifest["cursor_bounds"]["through_cursor"] == 10010
        assert manifest["verification"]["cursor_guard_passed"] is True
        assert manifest["purge"]["purge_status"] == "completed"

        # Check archive files on disk in target location: <vol_root>/2026/05/iot-rpc-rest-app/<batch_id>/
        final_dir = vol_root / "2026" / "05" / "iot-rpc-rest-app" / batch_db.id
        assert final_dir.is_dir()
        assert (final_dir / "data.jsonl.gz").is_file()
        assert (final_dir / "manifest.json").is_file()
        assert (final_dir / "checksum.sha256").is_file()

        # Check No-Financial-Purge Invariant: RemoteSession summary is untouched!
        assert "sess-2026-05-1" in session.remote_sessions
        assert session.remote_sessions["sess-2026-05-1"].status == "closed"

        # Check that high volume details were purged
        assert len(session.remote_events) == 0
        assert len(session.dev_tasks) == 0
        assert len(session.dev_events) == 0


# -------------------------------------------------------------------------
# Test 8: Crash at every phase & No-purge-on-failure
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_crash_at_every_phase_and_no_purge_on_failure():
    """Verify that failure at any stage marks batch as failed and aborts purge."""
    simulated_now = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)

    # Phase A: Cursor lag failure -> Purge must NOT execute
    session = ArchiveMockAsyncSession()
    ev = RemoteSessionEvent(
        event_id="evt-lag-1",
        cursor=15000,
        occurred_at=datetime(2026, 5, 10, 10, 0, 0, tzinfo=UTC),
        sn="SN-01",
        session_id="sess-1",
    )
    session.add(ev)

    with tempfile.TemporaryDirectory() as tmp_vol:
        vol = Path(tmp_vol).resolve()
        # Consumers passed cursor is 14000 < 15000 (lagging)
        with pytest.raises(CursorLagDetectedError):
            await run_archive_cycle(
                session=session,
                volume_root=vol,
                source_month="2026-05",
                consumers_passed_cursor=14000,
                dry_run=False,
                purge=True,
                now_utc=simulated_now,
            )

        # Batch marked as failed, events NOT purged
        assert len(session.remote_events) == 1
        failed_batches = [
            b for b in session.archive_batches.values() if b.state == "failed"
        ]
        assert len(failed_batches) == 1
        assert failed_batches[0].error_details["code"] == "CURSOR_LAG_DETECTED"

    # Phase B: Verification checksum mismatch failure -> Purge must NOT execute
    session = ArchiveMockAsyncSession()
    ev2 = RemoteSessionEvent(
        event_id="evt-chk-1",
        cursor=16000,
        occurred_at=datetime(2026, 5, 10, 10, 0, 0, tzinfo=UTC),
        sn="SN-01",
        session_id="sess-2",
    )
    session.add(ev2)

    with tempfile.TemporaryDirectory() as tmp_vol:
        vol = Path(tmp_vol).resolve()
        from core.archive import exporter

        orig_write = exporter.write_deterministic_jsonl_gz

        def corrupt_checksum_write(records, out_path):
            count, size, sha = orig_write(records, out_path)
            # Rewrite file with altered valid JSON to change SHA-256 without breaking gzip format
            tampered = dict(records[0])
            tampered["record_id"] = "tampered-different-id"
            orig_write([tampered], out_path)
            return count, size, sha

        exporter.write_deterministic_jsonl_gz = corrupt_checksum_write
        try:
            with pytest.raises(ChecksumMismatchError):
                await run_archive_cycle(
                    session=session,
                    volume_root=vol,
                    source_month="2026-05",
                    consumers_passed_cursor=17000,
                    dry_run=False,
                    purge=True,
                    now_utc=simulated_now,
                )
        finally:
            exporter.write_deterministic_jsonl_gz = orig_write

        # Data in DB remains completely safe and unpurged
        assert len(session.remote_events) == 1

    # Phase C: Restore sample corrupted JSON -> Purge must NOT execute
    session = ArchiveMockAsyncSession()
    ev3 = RemoteSessionEvent(
        event_id="evt-samp-1",
        cursor=17000,
        occurred_at=datetime(2026, 5, 10, 10, 0, 0, tzinfo=UTC),
        sn="SN-01",
        session_id="sess-3",
    )
    session.add(ev3)

    with tempfile.TemporaryDirectory() as tmp_vol:
        vol = Path(tmp_vol).resolve()

        def corrupt_gzip_write(records, out_path):
            count, size, sha = orig_write(records, out_path)
            with open(out_path, "wb") as f:
                f.write(b"not-a-valid-gzip-header")
            return count, size, sha

        exporter.write_deterministic_jsonl_gz = corrupt_gzip_write
        try:
            with pytest.raises(RestoreSampleFailedError):
                await run_archive_cycle(
                    session=session,
                    volume_root=vol,
                    source_month="2026-05",
                    consumers_passed_cursor=18000,
                    dry_run=False,
                    purge=True,
                    now_utc=simulated_now,
                )
        finally:
            exporter.write_deterministic_jsonl_gz = orig_write

        # Data in DB remains completely safe and unpurged
        assert len(session.remote_events) == 1


# -------------------------------------------------------------------------
# Test 9: Dry run mode smoke verification
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dry_run_mode_execution():
    """Verify dry_run executes staging export and verification without promotion or purge."""
    session = ArchiveMockAsyncSession()
    simulated_now = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)

    ev = RemoteSessionEvent(
        event_id="evt-dry-1",
        cursor=11000,
        occurred_at=datetime(2026, 5, 15, 10, 0, 0, tzinfo=UTC),
        sn="SN-DRY",
        session_id="sess-dry",
    )
    session.add(ev)

    with tempfile.TemporaryDirectory() as tmp_vol:
        vol = Path(tmp_vol).resolve()
        manifest, batch_db = await run_archive_cycle(
            session=session,
            volume_root=vol,
            source_month="2026-05",
            consumers_passed_cursor=12000,
            dry_run=True,
            purge=True,
            now_utc=simulated_now,
        )

        # Batch stays prepared, verification reported, DB unpurged
        assert batch_db.state == "prepared"
        assert len(session.remote_events) == 1
        assert manifest["verification"]["restore_sample_status"] == "passed"
        # Final directory not created in dry-run
        target_final_dir = vol / "2026" / "05" / "iot-rpc-rest-app" / batch_db.id
        assert not target_final_dir.exists()
