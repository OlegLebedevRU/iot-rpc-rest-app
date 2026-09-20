from __future__ import annotations

import calendar
from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Tuple

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.remote_sessions import RemoteSession
from ..schemas.remote_sessions import RemoteSessionLifecycleState
from .exceptions import (
    ActiveRecordsDetectedError,
    CursorLagDetectedError,
    DiskSpaceExhaustedError,
    HotRetentionViolationError,
    VolumeUnavailableError,
)


class RetentionGuard:
    """Enforces that only closed months strictly older than 3 full closed calendar months can be archived."""

    @staticmethod
    def parse_and_validate_source_month(
        source_month: str,
        now_utc: datetime | None = None,
        threshold_months: int = 3,
    ) -> Tuple[datetime, datetime]:
        """Validate source_month against now_utc and return (min_occurred_at, max_occurred_at) in UTC."""
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        elif now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)

        parts = source_month.split("-")
        if len(parts) != 2:
            raise ValueError(
                f"Invalid source_month format '{source_month}', expected 'YYYY-MM'"
            )
        try:
            year, month = int(parts[0]), int(parts[1])
            if not (1 <= month <= 12):
                raise ValueError
        except ValueError:
            raise ValueError(
                f"Invalid year/month values in source_month '{source_month}'"
            )

        diff_months = (now_utc.year - year) * 12 + (now_utc.month - month)
        # To be strictly older than 3 full closed months, diff_months must be >= 4
        # (e.g. In September (month 9), months 8, 7, 6 are the 3 full closed months;
        # month 5 (May) gives diff = 9 - 5 = 4 >= 4 -> OK).
        min_required_diff = threshold_months + 1
        if diff_months < min_required_diff:
            raise HotRetentionViolationError(
                f"Source month '{source_month}' is within hot retention window "
                f"(diff_months={diff_months} < {min_required_diff}, required > {threshold_months} full closed months)"
            )

        _, last_day = calendar.monthrange(year, month)
        min_dt = datetime(year, month, 1, 0, 0, 0, 0, tzinfo=timezone.utc)
        max_dt = datetime(
            year, month, last_day, 23, 59, 59, 999999, tzinfo=timezone.utc
        )
        return min_dt, max_dt


class ActiveRecordsGuard:
    """Ensures no active, starting, or open sessions exist in the target month window."""

    @staticmethod
    async def verify_no_active_records(
        session: AsyncSession,
        min_dt: datetime,
        max_dt: datetime,
    ) -> None:
        active_states = [
            RemoteSessionLifecycleState.REQUESTED.value,
            RemoteSessionLifecycleState.STARTING.value,
            RemoteSessionLifecycleState.ACTIVE.value,
            RemoteSessionLifecycleState.STOPPING.value,
        ]

        stmt = sa.select(sa.func.count(RemoteSession.id)).where(
            sa.and_(
                RemoteSession.created_at <= max_dt,
                sa.or_(
                    RemoteSession.closed_at.is_(None),
                    RemoteSession.closed_at >= min_dt,
                ),
                RemoteSession.status.in_(active_states),
            )
        )

        res = await session.execute(stmt)
        active_count = res.scalar() or 0
        if active_count > 0:
            raise ActiveRecordsDetectedError(
                f"Active or unclosed sessions ({active_count}) detected in time window {min_dt.isoformat()} - {max_dt.isoformat()}"
            )


class CursorGuard:
    """Verifies that mandatory downstream consumers have acknowledged records past through_cursor."""

    @staticmethod
    def verify_cursor_bounds(
        through_cursor: int | None,
        consumers_passed_cursor: int | None,
    ) -> None:
        if through_cursor is None or through_cursor == 0:
            return

        if consumers_passed_cursor is None or consumers_passed_cursor < through_cursor:
            raise CursorLagDetectedError(
                f"Cursor lag violation: consumers_passed_cursor ({consumers_passed_cursor}) "
                f"is behind through_cursor ({through_cursor})"
            )


class PathSecurityGuard:
    """Guards against directory traversal, symlink attacks, and disk capacity exhaustion."""

    @staticmethod
    def validate_and_resolve_path(
        volume_root: str | Path, subpath: str | Path | None = None
    ) -> Path:
        raw_root = Path(volume_root)
        resolved_root = raw_root.resolve()

        if resolved_root.is_symlink() or raw_root.is_symlink():
            raise VolumeUnavailableError(
                f"Symlinks are prohibited on archive volume: {volume_root}"
            )

        if subpath is None:
            target = resolved_root
        else:
            sub_str = str(subpath)
            if "\0" in sub_str or ".." in sub_str:
                raise VolumeUnavailableError(
                    f"Invalid path traversal sequence in subpath: {subpath}"
                )
            target = (resolved_root / subpath).resolve()

        try:
            target.relative_to(resolved_root)
        except ValueError:
            raise VolumeUnavailableError(
                f"Target path '{target}' escapes volume root '{resolved_root}'"
            )

        if target.is_symlink():
            raise VolumeUnavailableError(
                f"Symlinks are prohibited in archive path: {target}"
            )

        return target

    @staticmethod
    def check_disk_space(
        target_path: Path, min_free_bytes: int = 100 * 1024 * 1024
    ) -> None:
        # Check closest existing parent if target doesn't exist yet
        check_dir = target_path
        while not check_dir.exists() and check_dir.parent != check_dir:
            check_dir = check_dir.parent

        try:
            usage = shutil.disk_usage(check_dir)
        except Exception as exc:
            raise VolumeUnavailableError(
                f"Failed to check disk usage on '{check_dir}': {exc}"
            ) from exc

        if usage.free < min_free_bytes:
            raise DiskSpaceExhaustedError(
                f"Disk space exhausted on '{check_dir}': free={usage.free} bytes < required {min_free_bytes} bytes"
            )
