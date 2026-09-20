from __future__ import annotations

from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
import pytest

from core.models.archive import FinArchiveBatch
from core.models.db_helper import db_helper
from main import main_app


@pytest.mark.asyncio
async def test_internal_v1_archive_endpoints():
    """Verify internal REST endpoints for archive batches."""
    from tests.core.test_l4d_15b_archive import ArchiveMockAsyncSession

    mock_session = ArchiveMockAsyncSession()

    # Seed mock batch
    simulated_now = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)
    batch_id = "arch-iot-2026-05-test0001"
    manifest_data = {
        "archive_manifest_version": "1.0.0",
        "archive_batch_id": batch_id,
        "owner_project": "iot-rpc-rest-app",
        "schema_version": "1.0.0",
        "created_at_utc": simulated_now.isoformat(),
        "source_month": "2026-05",
        "time_range": {
            "min_occurred_at": "2026-05-01T00:00:00Z",
            "max_occurred_at": "2026-05-31T23:59:59.999999Z",
        },
        "cursor_bounds": {
            "min_cursor": 100,
            "max_cursor": 200,
            "through_cursor": 200,
            "consumers_passed_cursor": 250,
        },
        "record_types": ["iot_session_events"],
        "record_counts": {"iot_session_events": 100, "total_records": 100},
        "files": [
            {
                "path": "data.jsonl.gz",
                "size_bytes": 1024,
                "sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
                "record_count": 100,
                "compression": "gzip",
            }
        ],
        "compression": "gzip",
        "state": "purged",
        "verification": {
            "verified_at_utc": simulated_now.isoformat(),
            "verifier": "iot-archive-worker",
            "reread_records_count": 100,
            "reread_checksum_sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            "restore_sample_status": "passed",
            "cursor_guard_passed": True,
        },
        "purge": {
            "purged_at_utc": simulated_now.isoformat(),
            "purged_records_count": 100,
            "purge_status": "completed",
        },
        "error": None,
        "retention": {
            "retain_until_utc": "2029-09-21T12:00:00Z",
            "retention_years": 3,
            "backup_required": True,
        },
        "storage_layout": {
            "volume_root": "/mnt/l4desk-archive",
            "relative_path": f"2026/05/iot-rpc-rest-app/{batch_id}",
        },
    }

    batch_obj = FinArchiveBatch(
        id=batch_id,
        source_project="iot-rpc-rest-app",
        source_month="2026-05",
        manifest_version="1.0.0",
        schema_version="1.0.0",
        state="purged",
        total_records=100,
        data_size_bytes=1024,
        sha256_checksum="abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        min_occurred_at=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
        max_occurred_at=datetime(2026, 5, 31, 23, 59, 59, tzinfo=UTC),
        through_cursor=200,
        consumers_passed_cursor=250,
        manifest_payload=manifest_data,
        created_at=simulated_now,
        verified_at=simulated_now,
        purged_at=simulated_now,
    )
    mock_session.add(batch_obj)

    async def override_db():
        yield mock_session

    main_app.dependency_overrides[db_helper.session_factory] = override_db

    transport = ASGITransport(app=main_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. GET /api/internal/v1/archive/batches
        resp_list = await client.get("/api/internal/v1/archive/batches")
        assert resp_list.status_code == 200
        batches = resp_list.json()
        assert len(batches) == 1
        assert batches[0]["id"] == batch_id
        assert batches[0]["state"] == "purged"

        # 2. GET /api/internal/v1/archive/batches/{id}
        resp_detail = await client.get(f"/api/internal/v1/archive/batches/{batch_id}")
        assert resp_detail.status_code == 200
        detail = resp_detail.json()
        assert detail["id"] == batch_id
        assert detail["manifest_payload"]["archive_batch_id"] == batch_id

        # 3. GET /api/internal/v1/archive/batches/{id}/manifest
        resp_mf = await client.get(
            f"/api/internal/v1/archive/batches/{batch_id}/manifest"
        )
        assert resp_mf.status_code == 200
        mf = resp_mf.json()
        assert mf["archive_manifest_version"] == "1.0.0"
        assert mf["state"] == "purged"

        # 4. POST /api/internal/v1/archive/run with hot retention month (e.g. 2026-08) -> 400
        resp_bad = await client.post(
            "/api/internal/v1/archive/run",
            json={
                "source_month": "2026-08",
                "consumers_passed_cursor": 500,
                "dry_run": False,
                "purge": False,
            },
        )
        assert resp_bad.status_code == 400
        err = resp_bad.json()
        assert err["detail"]["code"] == "HOT_RETENTION_VIOLATION"

    main_app.dependency_overrides.clear()
