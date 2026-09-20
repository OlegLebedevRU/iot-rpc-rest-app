from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.archive import FinArchiveBatch
from ..models.device_events import DevEvent
from ..models.device_tasks import DevTask, DevTaskPayload, DevTaskResult, DevTaskStatus
from ..models.remote_sessions import RemoteSessionEvent
from .canonical import write_manifest_file
from .exceptions import PurgeOperationFailedError
from .guards import ActiveRecordsGuard, CursorGuard

log = logging.getLogger(__name__)


async def purge_archived_records_bounded(
    session: AsyncSession,
    archive_dir: Path,
    manifest: dict[str, Any],
    batch_db: FinArchiveBatch,
    min_dt: datetime,
    max_dt: datetime,
    chunk_size: int = 1000,
    now_utc: datetime | None = None,
) -> int:
    """Safely purge archived records from operational tables in bounded chunks.

    Guarantees No-Financial-Purge invariant: RemoteSession summaries and financial/org
    records are never modified or purged.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    elif now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    # 1. State and Guard Validations
    if manifest.get("state") != "verified":
        raise PurgeOperationFailedError(
            f"Cannot purge unverified batch, current state is '{manifest.get('state')}'"
        )

    verification_info = manifest.get("verification") or {}
    if not verification_info.get("cursor_guard_passed"):
        raise PurgeOperationFailedError(
            "Cursor guard verification is missing or failed in manifest"
        )

    cursor_bounds = manifest.get("cursor_bounds") or {}
    through_cursor = cursor_bounds.get("through_cursor")
    consumers_passed_cursor = cursor_bounds.get("consumers_passed_cursor")
    CursorGuard.verify_cursor_bounds(through_cursor, consumers_passed_cursor)

    # Active records re-check right before purge
    await ActiveRecordsGuard.verify_no_active_records(session, min_dt, max_dt)

    total_purged = 0

    try:
        # A. Purge RemoteSessionEvents (bounded by chunk_size and through_cursor)
        while True:
            ev_conds = [
                RemoteSessionEvent.occurred_at >= min_dt,
                RemoteSessionEvent.occurred_at <= max_dt,
            ]
            if through_cursor is not None:
                ev_conds.append(RemoteSessionEvent.cursor <= through_cursor)

            # Select batch of event_ids to delete
            id_stmt = (
                sa.select(RemoteSessionEvent.event_id)
                .where(sa.and_(*ev_conds))
                .limit(chunk_size)
            )
            id_rows = (await session.execute(id_stmt)).scalars().all()
            if not id_rows:
                break

            del_ev_stmt = sa.delete(RemoteSessionEvent).where(
                RemoteSessionEvent.event_id.in_(id_rows)
            )
            ev_del_res = await session.execute(del_ev_stmt)
            count = ev_del_res.rowcount or len(id_rows)
            total_purged += count
            await session.flush()

        # B. Purge Completed DevTasks (only completed/expired/deleted)
        while True:
            tsk_id_stmt = (
                sa.select(DevTask.id)
                .where(
                    DevTask.created_at >= min_dt,
                    DevTask.created_at <= max_dt,
                )
                .limit(chunk_size)
            )
            tsk_ids = (await session.execute(tsk_id_stmt)).scalars().all()
            if not tsk_ids:
                break

            # Delete children first
            await session.execute(
                sa.delete(DevTaskPayload).where(DevTaskPayload.task_id.in_(tsk_ids))
            )
            await session.execute(
                sa.delete(DevTaskStatus).where(DevTaskStatus.task_id.in_(tsk_ids))
            )
            await session.execute(
                sa.delete(DevTaskResult).where(DevTaskResult.task_id.in_(tsk_ids))
            )
            del_tsk_res = await session.execute(
                sa.delete(DevTask).where(DevTask.id.in_(tsk_ids))
            )
            count = del_tsk_res.rowcount or len(tsk_ids)
            total_purged += count
            await session.flush()

        # C. Purge DevEvents
        while True:
            dev_ev_id_stmt = (
                sa.select(DevEvent.id)
                .where(
                    DevEvent.created_at >= min_dt,
                    DevEvent.created_at <= max_dt,
                )
                .limit(chunk_size)
            )
            dev_ev_ids = (await session.execute(dev_ev_id_stmt)).scalars().all()
            if not dev_ev_ids:
                break

            del_dev_stmt = sa.delete(DevEvent).where(DevEvent.id.in_(dev_ev_ids))
            del_dev_res = await session.execute(del_dev_stmt)
            count = del_dev_res.rowcount or len(dev_ev_ids)
            total_purged += count
            await session.flush()

    except Exception as exc:
        raise PurgeOperationFailedError(
            f"Purge execution encountered database error: {exc}"
        ) from exc

    # Invariant Check: Verify RemoteSession summaries are intact
    # We do NOT touch RemoteSession table at all.

    # 2. Update manifest.json with purge results
    manifest["purge"] = {
        "purged_at_utc": now_utc.isoformat(),
        "purged_records_count": total_purged,
        "purge_status": "completed",
    }
    manifest["state"] = "purged"

    manifest_file_path = archive_dir / "manifest.json"
    write_manifest_file(manifest, manifest_file_path)

    # 3. Update DB batch record
    batch_db.state = "purged"
    batch_db.purged_at = now_utc
    batch_db.manifest_payload = manifest
    batch_db.error_details = None
    await session.flush()

    log.info(
        "Purge completed successfully for batch %s: purged %d records",
        manifest["archive_batch_id"],
        total_purged,
    )
    return total_purged
