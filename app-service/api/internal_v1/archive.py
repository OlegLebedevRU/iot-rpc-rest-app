from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from core.archive import run_archive_cycle
from core.config import settings
from core.models import FinArchiveBatch, db_helper
from core.schemas.archive import (
    ArchiveBatchDetail,
    ArchiveBatchSummary,
    ArchiveRunRequest,
)

router = APIRouter(
    prefix=settings.api.internal_v1.archive,
    tags=["Internal Monthly Archive"],
)

log = logging.getLogger(__name__)


@router.post(
    "/run",
    response_model=ArchiveBatchDetail,
    summary="Trigger monthly archive cycle",
    status_code=status.HTTP_200_OK,
)
async def run_archive_endpoint(
    req: ArchiveRunRequest,
    session: AsyncSession = Depends(db_helper.session_factory),
) -> Any:
    volume_root = req.volume_root or settings.archive.volume_root
    try:
        manifest, batch_db = await run_archive_cycle(
            session=session,
            volume_root=volume_root,
            source_month=req.source_month,
            consumers_passed_cursor=req.consumers_passed_cursor,
            dry_run=req.dry_run,
            purge=req.purge,
            chunk_size=settings.archive.chunk_size,
            sample_size=settings.archive.sample_restore_size,
        )
        await session.commit()
        return batch_db
    except Exception as exc:
        await session.rollback()
        err_code = getattr(exc, "code", "ARCHIVE_FAILED")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": err_code, "message": str(exc)},
        ) from exc


@router.get(
    "/batches",
    response_model=list[ArchiveBatchSummary],
    summary="List archive batches",
)
async def list_archive_batches(
    source_month: str | None = Query(None, description="Filter by YYYY-MM"),
    state: str | None = Query(
        None, description="Filter by state (prepared, verified, purged, failed)"
    ),
    session: AsyncSession = Depends(db_helper.session_factory),
) -> Any:
    stmt = sa.select(FinArchiveBatch).where(
        FinArchiveBatch.source_project == "iot-rpc-rest-app"
    )
    if source_month:
        stmt = stmt.where(FinArchiveBatch.source_month == source_month)
    if state:
        stmt = stmt.where(FinArchiveBatch.state == state)
    stmt = stmt.order_by(FinArchiveBatch.created_at.desc())

    res = await session.execute(stmt)
    return res.scalars().all()


@router.get(
    "/batches/{batch_id}",
    response_model=ArchiveBatchDetail,
    summary="Get archive batch details",
)
async def get_archive_batch(
    batch_id: str,
    session: AsyncSession = Depends(db_helper.session_factory),
) -> Any:
    batch = await session.get(FinArchiveBatch, (batch_id, "iot-rpc-rest-app"))
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Archive batch not found"
        )
    return batch


@router.get(
    "/batches/{batch_id}/manifest",
    summary="Get canonical manifest payload for an archive batch",
)
async def get_archive_batch_manifest(
    batch_id: str,
    session: AsyncSession = Depends(db_helper.session_factory),
) -> dict[str, Any]:
    batch = await session.get(FinArchiveBatch, (batch_id, "iot-rpc-rest-app"))
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Archive batch not found"
        )
    return batch.manifest_payload
