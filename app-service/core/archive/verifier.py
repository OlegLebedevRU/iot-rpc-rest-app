from __future__ import annotations

from datetime import datetime, timezone
import gzip
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.archive import FinArchiveBatch
from .canonical import (
    compute_file_sha256,
    write_manifest_file,
)
from .exceptions import (
    AtomicRenameFailedError,
    ChecksumMismatchError,
    CountMismatchError,
    RestoreSampleFailedError,
)
from .guards import CursorGuard, PathSecurityGuard


async def verify_and_promote_staging(
    session: AsyncSession,
    staging_dir: Path,
    volume_root: Path,
    manifest: dict[str, Any],
    batch_db: FinArchiveBatch,
    sample_size: int = 10,
    now_utc: datetime | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Perform full reread, checksum verification, sample restore, cursor guard, and atomic promotion."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    elif now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    data_file_path = staging_dir / "data.jsonl.gz"
    checksum_file_path = staging_dir / "checksum.sha256"

    if not data_file_path.is_file():
        raise FileNotFoundError(
            f"Missing data.jsonl.gz in staging folder: {staging_dir}"
        )
    if not checksum_file_path.is_file():
        raise FileNotFoundError(
            f"Missing checksum.sha256 in staging folder: {staging_dir}"
        )

    # 1. Full reread and count
    reread_count = 0
    sample_records: list[dict[str, Any]] = []

    try:
        with gzip.open(data_file_path, "rt", encoding="utf-8") as gz_in:
            for line in gz_in:
                if reread_count < sample_size:
                    sample_records.append(json.loads(line))
                reread_count += 1
    except Exception as exc:
        raise RestoreSampleFailedError(
            f"Failed during full reread of archive: {exc}"
        ) from exc

    # 2. Re-compute SHA-256
    reread_sha256 = compute_file_sha256(data_file_path)

    expected_sha256 = manifest["files"][0]["sha256"]
    expected_count = manifest["files"][0]["record_count"]

    if reread_sha256 != expected_sha256:
        raise ChecksumMismatchError(
            f"Checksum mismatch: reread={reread_sha256} != expected={expected_sha256}"
        )
    if reread_count != expected_count:
        raise CountMismatchError(
            f"Record count mismatch: reread={reread_count} != expected={expected_count}"
        )

    # Verify checksum.sha256 file content
    with open(checksum_file_path, "r", encoding="utf-8") as f:
        stored_checksum_content = f.read().strip()
    if not stored_checksum_content.startswith(reread_sha256):
        raise ChecksumMismatchError(
            f"checksum.sha256 file content '{stored_checksum_content}' does not match '{reread_sha256}'"
        )

    # 3. Sample restore validation
    for sample in sample_records:
        if not isinstance(sample, dict):
            raise RestoreSampleFailedError("Sample record is not a valid JSON object")
        for req_key in (
            "record_type",
            "record_id",
            "occurred_at_utc",
            "source_project",
        ):
            if req_key not in sample:
                raise RestoreSampleFailedError(
                    f"Sample record missing required field '{req_key}'"
                )

    # 4. Cursor Guard
    cursor_bounds = manifest.get("cursor_bounds") or {}
    through_cursor = cursor_bounds.get("through_cursor")
    consumers_passed_cursor = cursor_bounds.get("consumers_passed_cursor")
    CursorGuard.verify_cursor_bounds(through_cursor, consumers_passed_cursor)

    # 5. Atomic Promotion
    source_month = manifest["source_month"]
    year_str, month_str = source_month.split("-")
    batch_id = manifest["archive_batch_id"]

    target_subpath = Path(year_str) / month_str / "iot-rpc-rest-app" / batch_id
    final_dir = PathSecurityGuard.validate_and_resolve_path(volume_root, target_subpath)
    final_dir.parent.mkdir(parents=True, exist_ok=True)

    try:
        if final_dir.exists():
            # If already exists in final path, rename safely
            temp_old = final_dir.with_name(
                f".old_{batch_id}_{int(now_utc.timestamp())}"
            )
            os.replace(final_dir, temp_old)
        os.replace(staging_dir, final_dir)
    except Exception as exc:
        raise AtomicRenameFailedError(
            f"Atomic rename failed from {staging_dir} to {final_dir}: {exc}"
        ) from exc

    # 6. Update manifest to verified state
    manifest["verification"] = {
        "verified_at_utc": now_utc.isoformat(),
        "verifier": "iot-archive-worker",
        "reread_records_count": reread_count,
        "reread_checksum_sha256": reread_sha256,
        "restore_sample_status": "passed",
        "cursor_guard_passed": True,
    }
    manifest["state"] = "verified"

    final_manifest_path = final_dir / "manifest.json"
    write_manifest_file(manifest, final_manifest_path)

    # Update DB state
    batch_db.state = "verified"
    batch_db.verified_at = now_utc
    batch_db.manifest_payload = manifest
    batch_db.error_details = None
    await session.flush()

    return final_dir, manifest
