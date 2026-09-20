from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import logging
from pathlib import Path
import sys

# Add app-service to sys.path
app_service_dir = Path(__file__).resolve().parent.parent
if str(app_service_dir) not in sys.path:
    sys.path.insert(0, str(app_service_dir))

from core.archive import run_archive_cycle  # noqa: E402
from core.config import settings  # noqa: E402
from core.models import db_helper  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("archive-worker")


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Leo4 IoT Platform Monthly Archive Worker"
    )
    parser.add_argument(
        "--month", type=str, required=True, help="Target closed month in YYYY-MM format"
    )
    parser.add_argument(
        "--volume-root",
        type=str,
        default=settings.archive.volume_root,
        help="Root path for archive mount",
    )
    parser.add_argument(
        "--consumers-cursor",
        type=int,
        default=None,
        help="Consumers acknowledged cursor (MenuBuilder billing cursor)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=settings.archive.dry_run,
        help="Run export and verification in staging without promotion or purge",
    )
    parser.add_argument(
        "--purge",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Perform bounded purge of archived records upon verification",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force execution even if archive worker is disabled in settings",
    )
    parser.add_argument(
        "--now-utc",
        type=str,
        default=None,
        help="Simulate execution time (ISO format) for retention testing",
    )

    args = parser.parse_args()

    if not settings.archive.enabled and not args.force and not args.dry_run:
        log.warning(
            "Archive worker is disabled in configuration (APP_CONFIG__ARCHIVE__ENABLED=false). "
            "Use --force or --dry-run to bypass."
        )
        return 1

    simulated_now: datetime | None = None
    if args.now_utc:
        simulated_now = datetime.fromisoformat(args.now_utc).astimezone(timezone.utc)

    log.info(
        "Starting archive cycle for month=%s, volume=%s, dry_run=%s, purge=%s, consumers_cursor=%s",
        args.month,
        args.volume_root,
        args.dry_run,
        args.purge,
        args.consumers_cursor,
    )

    async with db_helper.session_factory() as session:
        async with session.begin():
            try:
                manifest, batch_db = await run_archive_cycle(
                    session=session,
                    volume_root=args.volume_root,
                    source_month=args.month,
                    consumers_passed_cursor=args.consumers_cursor,
                    dry_run=args.dry_run,
                    purge=args.purge,
                    now_utc=simulated_now,
                    chunk_size=settings.archive.chunk_size,
                    sample_size=settings.archive.sample_restore_size,
                )
                log.info(
                    "Archive cycle finished successfully: batch_id=%s, state=%s, total_records=%s",
                    batch_db.id,
                    batch_db.state,
                    batch_db.total_records,
                )
                return 0
            except Exception as exc:
                log.exception("Archive worker execution failed: %s", exc)
                return 2


if __name__ == "__main__":
    code = asyncio.run(main())
    sys.exit(code)
