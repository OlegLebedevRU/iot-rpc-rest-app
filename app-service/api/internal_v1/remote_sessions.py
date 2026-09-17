from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.internal_v1.internal_depends import (
    Internal_Auth_dep,
    Session_dep,
)
from core.schemas.remote_sessions import (
    RemoteSessionCreate,
    RemoteSessionEventFeedResponse,
    RemoteSessionReconciliationResponse,
    RemoteSessionResponse,
    RemoteSessionStop,
)
from core.services.remote_session_event_service import remote_session_event_service

router = APIRouter(tags=["Internal Remote Sessions & Events"])


@router.get(
    "/remote-session-events",
    response_model=RemoteSessionEventFeedResponse,
    summary="Query durable remote session event feed with monotonic cursor",
)
async def get_remote_session_events(
    session: Session_dep,
    _: Internal_Auth_dep,
    after: int = Query(0, ge=0, description="Return events strictly after this cursor"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of events to return"),
    tenant_id: int | None = Query(None, description="Filter by tenant / organization ID"),
    sn: str | None = Query(None, description="Filter by device serial number"),
    session_id: str | None = Query(None, description="Filter by session ID"),
    event_type: str | None = Query(None, description="Filter by event type"),
) -> RemoteSessionEventFeedResponse:
    try:
        return await remote_session_event_service.get_event_feed(
            session,
            after=after,
            limit=limit,
            tenant_id=tenant_id,
            sn=sn,
            session_id=session_id,
            event_type=event_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/remote-session-events/reconciliation",
    response_model=RemoteSessionReconciliationResponse,
    summary="Reconciliation summary and cryptographic SHA-256 digest of event feed facts",
)
async def get_remote_session_events_reconciliation(
    session: Session_dep,
    _: Internal_Auth_dep,
    tenant_id: int | None = Query(None, description="Filter by tenant ID"),
    from_cursor: int | None = Query(None, ge=0, description="Start cursor (inclusive)"),
    to_cursor: int | None = Query(None, ge=0, description="End cursor (inclusive)"),
    from_time: datetime | None = Query(None, description="Start time UTC"),
    to_time: datetime | None = Query(None, description="End time UTC"),
) -> RemoteSessionReconciliationResponse:
    return await remote_session_event_service.get_reconciliation_summary(
        session,
        tenant_id=tenant_id,
        from_cursor=from_cursor,
        to_cursor=to_cursor,
        from_time=from_time,
        to_time=to_time,
    )


@router.post(
    "/remote-sessions",
    response_model=RemoteSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a remote session with idempotency on operation_id",
)
async def create_remote_session(
    data: RemoteSessionCreate,
    session: Session_dep,
    _: Internal_Auth_dep,
) -> RemoteSessionResponse:
    try:
        created = await remote_session_event_service.create_session(session, data)
        await session.commit()
        await session.refresh(created)
        return RemoteSessionResponse.model_validate(created)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/remote-sessions/{session_id}",
    response_model=RemoteSessionResponse,
    summary="Get durable facts for a remote session",
)
async def get_remote_session(
    session_id: str,
    session: Session_dep,
    _: Internal_Auth_dep,
) -> RemoteSessionResponse:
    rec = await remote_session_event_service.get_session(session, session_id)
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Remote session '{session_id}' not found",
        )
    return RemoteSessionResponse.model_validate(rec)


@router.post(
    "/remote-sessions/{session_id}/stop",
    response_model=RemoteSessionResponse,
    summary="Stop a remote session idempotently",
)
async def stop_remote_session(
    session_id: str,
    session: Session_dep,
    _: Internal_Auth_dep,
    body: RemoteSessionStop = RemoteSessionStop(),
) -> RemoteSessionResponse:
    rec = await remote_session_event_service.stop_session(session, session_id, body)
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Remote session '{session_id}' not found",
        )
    await session.commit()
    await session.refresh(rec)
    return RemoteSessionResponse.model_validate(rec)
