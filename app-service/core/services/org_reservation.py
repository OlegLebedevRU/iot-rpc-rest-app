"""Atomic, replayable organization ID reservation for MenuBuilder."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Org, OrgReservation
from core.schemas.provisioning import OrgReservationRequest, OrgReservationResponse

_ORG_ALLOCATION_LOCK = 4_528_047_185_704_251
_MAX_ORG_ID = 2_147_483_647


async def reserve_org_id(
    session: AsyncSession, request: OrgReservationRequest
) -> OrgReservationResponse:
    """Reserve one IoT org ID before MenuBuilder creates its matching tenant.

    The database lock serializes reservations. The unique tb_orgs.org_id
    constraint also protects against other IoT writers that do not take it.
    """
    await session.execute(select(func.pg_advisory_xact_lock(_ORG_ALLOCATION_LOCK)))
    existing = await session.get(OrgReservation, request.operation_id)
    if existing is not None:
        if existing.source_project != "MenuBuilder" or (
            request.requested_org_id is not None
            and existing.org_id != request.requested_org_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "org_reservation_operation_conflict"},
            )
        reserved_org_id = existing.org_id
        # Release the advisory lock immediately on an idempotent replay.
        await session.rollback()
        return OrgReservationResponse(
            operation_id=request.operation_id,
            org_id=reserved_org_id,
            replayed=True,
        )

    if request.requested_org_id is not None:
        if request.requested_org_id < request.minimum_org_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "org_id_below_minimum"},
            )
        candidate = request.requested_org_id
    else:
        highest = await session.scalar(select(func.max(Org.org_id))) or 0
        candidate = max(highest + 1, request.minimum_org_id)

    while candidate <= _MAX_ORG_ID:
        inserted = await session.scalar(
            pg_insert(Org)
            .values(
                org_id=candidate,
                name=f"MenuBuilder reservation {candidate}",
                is_deleted=False,
            )
            .on_conflict_do_nothing(index_elements=["org_id"])
            .returning(Org.org_id)
        )
        if inserted is not None:
            session.add(
                OrgReservation(
                    operation_id=request.operation_id,
                    source_project="MenuBuilder",
                    org_id=candidate,
                )
            )
            await session.commit()
            return OrgReservationResponse(
                operation_id=request.operation_id,
                org_id=candidate,
                replayed=False,
            )
        if request.requested_org_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "org_id_already_in_use"},
            )
        candidate += 1

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "org_id_space_exhausted"},
    )
