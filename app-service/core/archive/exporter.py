from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import time
from typing import Any
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.archive import FinArchiveBatch
from ..models.device_events import DevEvent
from ..models.device_tasks import DevTask
from ..models.remote_sessions import RemoteSessionEvent
from .canonical import (
    format_checksum_content,
    write_deterministic_jsonl_gz,
    write_manifest_file,
)
from .guards import PathSecurityGuard


def generate_batch_id(source_month: str, seed: str | None = None) -> str:
    """Generate canonical batch ID like arch-iot-2026-05-b91c84f2."""
    if seed:
        suffix = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]
    else:
        suffix = uuid.uuid4().hex[:8]
    return f"arch-iot-{source_month}-{suffix}"


async def fetch_archive_records(
    session: AsyncSession,
    min_dt: datetime,
    max_dt: datetime,
) -> list[dict[str, Any]]:
    """Fetch high-volume technical details for the target closed month."""
    records: list[dict[str, Any]] = []

    # 1. IoT Session Events (cursor-tracked)
    ev_stmt = (
        sa.select(RemoteSessionEvent)
        .where(
            RemoteSessionEvent.occurred_at >= min_dt,
            RemoteSessionEvent.occurred_at <= max_dt,
        )
        .order_by(RemoteSessionEvent.cursor.asc(), RemoteSessionEvent.occurred_at.asc())
    )
    ev_res = await session.execute(ev_stmt)
    for ev in ev_res.scalars().all():
        term_id_val = None
        if ev.terminal_id is not None:
            try:
                term_id_val = int(ev.terminal_id)
            except ValueError:
                term_id_val = None

        occ_utc = ev.occurred_at.astimezone(timezone.utc)
        records.append(
            {
                "record_type": "iot_session_events",
                "record_id": ev.event_id,
                "occurred_at_utc": occ_utc.isoformat(),
                "cursor": ev.cursor,
                "tenant_id": ev.tenant_id,
                "terminal_id": term_id_val,
                "sn": ev.sn,
                "session_id": ev.session_id,
                "source_project": "iot-rpc-rest-app",
                "payload": ev.payload or {},
            }
        )

    # 2. RPC Transitions (completed device tasks)
    tsk_stmt = (
        sa.select(DevTask)
        .where(
            DevTask.created_at >= min_dt,
            DevTask.created_at <= max_dt,
        )
        .order_by(DevTask.id.asc())
    )
    tsk_res = await session.execute(tsk_stmt)
    for tsk in tsk_res.scalars().all():
        occ_dt = tsk.deleted_at or tsk.created_at
        occ_utc = occ_dt.astimezone(timezone.utc)
        records.append(
            {
                "record_type": "rpc_transitions",
                "record_id": f"tsk-{tsk.id}",
                "occurred_at_utc": occ_utc.isoformat(),
                "cursor": None,
                "tenant_id": None,
                "terminal_id": None,
                "sn": str(tsk.device_id) if tsk.device_id else None,
                "session_id": None,
                "source_project": "iot-rpc-rest-app",
                "payload": {
                    "task_id": str(tsk.id),
                    "method_code": tsk.method_code,
                    "device_id": tsk.device_id,
                    "is_deleted": tsk.is_deleted,
                },
            }
        )

    # 3. Presence Events (device lifecycle events)
    dev_stmt = (
        sa.select(DevEvent)
        .where(
            DevEvent.created_at >= min_dt,
            DevEvent.created_at <= max_dt,
        )
        .order_by(DevEvent.id.asc())
    )
    dev_res = await session.execute(dev_stmt)
    for dev_ev in dev_res.scalars().all():
        occ_utc = dev_ev.created_at.astimezone(timezone.utc)
        records.append(
            {
                "record_type": "presence_events",
                "record_id": f"dev-evt-{dev_ev.id}",
                "occurred_at_utc": occ_utc.isoformat(),
                "cursor": None,
                "tenant_id": None,
                "terminal_id": None,
                "sn": str(dev_ev.device_id) if dev_ev.device_id else None,
                "session_id": None,
                "source_project": "iot-rpc-rest-app",
                "payload": dev_ev.payload or {},
            }
        )

    # Deterministic multi-key sort
    records.sort(
        key=lambda r: (r["occurred_at_utc"], r["cursor"] or -1, r["record_id"])
    )
    return records


async def export_batch_to_staging(
    session: AsyncSession,
    volume_root: Path,
    source_month: str,
    min_dt: datetime,
    max_dt: datetime,
    batch_id: str,
    records: list[dict[str, Any]],
    consumers_passed_cursor: int | None = None,
    now_utc: datetime | None = None,
) -> tuple[Path, dict[str, Any], FinArchiveBatch]:
    """Export records deterministically into a staging folder .tmp_<batch_id>_<timestamp>."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    elif now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    timestamp_suffix = int(time.time() * 1000)
    staging_dir_name = f".tmp_{batch_id}_{timestamp_suffix}"
    staging_dir = PathSecurityGuard.validate_and_resolve_path(
        volume_root, staging_dir_name
    )
    staging_dir.mkdir(parents=True, exist_ok=True)

    # Compute bounds and counts
    counts_by_type: dict[str, int] = {}
    cursors: list[int] = []
    earliest_dt = max_dt
    latest_dt = min_dt

    for r in records:
        rtype = r["record_type"]
        counts_by_type[rtype] = counts_by_type.get(rtype, 0) + 1
        if r.get("cursor") is not None:
            cursors.append(r["cursor"])
        r_dt = datetime.fromisoformat(r["occurred_at_utc"])
        if r_dt < earliest_dt:
            earliest_dt = r_dt
        if r_dt > latest_dt:
            latest_dt = r_dt

    if not records:
        earliest_dt = min_dt
        latest_dt = max_dt

    min_cursor = min(cursors) if cursors else None
    max_cursor = max(cursors) if cursors else None
    through_cursor = max_cursor

    total_records = len(records)
    record_counts = {**counts_by_type, "total_records": total_records}
    record_types = sorted(list(counts_by_type.keys()))

    # Write data.jsonl.gz
    data_file_path = staging_dir / "data.jsonl.gz"
    rec_count, file_size, file_sha256 = write_deterministic_jsonl_gz(
        records, data_file_path
    )

    # Write checksum.sha256
    checksum_file_path = staging_dir / "checksum.sha256"
    checksum_content = format_checksum_content(file_sha256, "data.jsonl.gz")
    with open(checksum_file_path, "w", encoding="utf-8") as f:
        f.write(checksum_content)

    year_str, month_str = source_month.split("-")
    retain_until = datetime(
        now_utc.year + 3,
        now_utc.month,
        now_utc.day,
        now_utc.hour,
        now_utc.minute,
        now_utc.second,
        tzinfo=timezone.utc,
    )
    relative_path = f"{year_str}/{month_str}/iot-rpc-rest-app/{batch_id}"

    manifest: dict[str, Any] = {
        "archive_manifest_version": "1.0.0",
        "archive_batch_id": batch_id,
        "owner_project": "iot-rpc-rest-app",
        "schema_version": "1.0.0",
        "created_at_utc": now_utc.isoformat(),
        "source_month": source_month,
        "time_range": {
            "min_occurred_at": earliest_dt.isoformat(),
            "max_occurred_at": latest_dt.isoformat(),
        },
        "cursor_bounds": {
            "min_cursor": min_cursor,
            "max_cursor": max_cursor,
            "through_cursor": through_cursor,
            "consumers_passed_cursor": consumers_passed_cursor
            if consumers_passed_cursor is not None
            else 0,
        },
        "record_types": record_types,
        "record_counts": record_counts,
        "files": [
            {
                "path": "data.jsonl.gz",
                "size_bytes": file_size,
                "sha256": file_sha256,
                "record_count": rec_count,
                "compression": "gzip",
            }
        ],
        "compression": "gzip",
        "state": "prepared",
        "verification": None,
        "purge": {
            "purged_at_utc": None,
            "purged_records_count": 0,
            "purge_status": "pending",
        },
        "error": None,
        "retention": {
            "retain_until_utc": retain_until.isoformat(),
            "retention_years": 3,
            "backup_required": True,
        },
        "storage_layout": {
            "volume_root": str(volume_root).replace("\\", "/"),
            "relative_path": relative_path,
        },
    }

    # Write initial manifest.json
    manifest_file_path = staging_dir / "manifest.json"
    write_manifest_file(manifest, manifest_file_path)

    # Record or update in fin_archive_batches
    batch_db = await session.get(FinArchiveBatch, (batch_id, "iot-rpc-rest-app"))
    if not batch_db:
        batch_db = FinArchiveBatch(
            id=batch_id,
            source_project="iot-rpc-rest-app",
            source_month=source_month,
            manifest_version="1.0.0",
            schema_version="1.0.0",
            state="prepared",
            total_records=total_records,
            data_size_bytes=file_size,
            sha256_checksum=file_sha256,
            min_occurred_at=earliest_dt,
            max_occurred_at=latest_dt,
            through_cursor=through_cursor,
            consumers_passed_cursor=consumers_passed_cursor or 0,
            manifest_payload=manifest,
            created_at=now_utc,
        )
        session.add(batch_db)
    else:
        batch_db.state = "prepared"
        batch_db.total_records = total_records
        batch_db.data_size_bytes = file_size
        batch_db.sha256_checksum = file_sha256
        batch_db.min_occurred_at = earliest_dt
        batch_db.max_occurred_at = latest_dt
        batch_db.through_cursor = through_cursor
        batch_db.consumers_passed_cursor = consumers_passed_cursor or 0
        batch_db.manifest_payload = manifest
        batch_db.error_details = None

    await session.flush()
    return staging_dir, manifest, batch_db
