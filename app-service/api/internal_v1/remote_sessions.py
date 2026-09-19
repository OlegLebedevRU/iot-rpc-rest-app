from __future__ import annotations

from datetime import datetime
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
import sqlalchemy as sa

from api.internal_v1.internal_depends import (
    Internal_Auth_dep,
    Session_dep,
)
from core.schemas.remote_sessions import (
    ConsoleCommandCompleteRequest,
    ConsoleCommandStartRequest,
    ConsoleCommandTimeoutRequest,
    RemoteSessionCreate,
    RemoteSessionEventFeedResponse,
    RemoteSessionReconciliationResponse,
    RemoteSessionResponse,
    RemoteSessionStart,
    RemoteSessionStop,
    SessionConflictDetail,
)
from core.services.remote_session_event_service import (
    ConsoleCommandForbiddenError,
    RemoteSessionConflictError,
    remote_session_event_service,
)

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
    responses={
        409: {"model": SessionConflictDetail, "description": "Device already has an active or starting session"},
    },
    summary="Create a remote session with idempotency on operation_id and mutual exclusion on device",
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
    except RemoteSessionConflictError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.to_dict(),
        ) from exc
    except sa.exc.IntegrityError as exc:
        await session.rollback()
        active = await remote_session_event_service.get_active_session_for_sn(session, data.sn)
        if active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=RemoteSessionConflictError(
                    active_session_id=active.session_id,
                    active_session_type=active.session_type,
                    active_status=active.status,
                    sn=data.sn,
                ).to_dict(),
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "session_busy",
                "message": f"Conflict on device '{data.sn}': an active session is already starting or running",
                "sn": data.sn,
            },
        ) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/remote-sessions/{session_id}/start",
    response_model=RemoteSessionResponse,
    summary="Advance remote session lifecycle: requested -> starting -> active",
)
async def start_remote_session(
    session_id: str,
    session: Session_dep,
    _: Internal_Auth_dep,
    body: RemoteSessionStart = RemoteSessionStart(),
) -> RemoteSessionResponse:
    try:
        rec = await remote_session_event_service.start_session(session, session_id, body)
        await session.commit()
        await session.refresh(rec)
        return RemoteSessionResponse.model_validate(rec)
    except ValueError as exc:
        await session.rollback()
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg) from exc
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg) from exc


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
    summary="Stop a remote session with graceful stop flow",
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


@router.post(
    "/remote-sessions/{session_id}/heartbeat",
    response_model=RemoteSessionResponse,
    summary="Update last heartbeat timestamp to prevent stale session eviction",
)
async def heartbeat_remote_session(
    session_id: str,
    session: Session_dep,
    _: Internal_Auth_dep,
) -> RemoteSessionResponse:
    rec = await remote_session_event_service.heartbeat(session, session_id)
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Remote session '{session_id}' not found",
        )
    await session.commit()
    await session.refresh(rec)
    return RemoteSessionResponse.model_validate(rec)


@router.post(
    "/remote-sessions/{session_id}/commands/start",
    summary="Start a console command in an active console session",
)
async def start_console_command(
    session_id: str,
    body: ConsoleCommandStartRequest,
    session: Session_dep,
    _: Internal_Auth_dep,
) -> dict[str, Any]:
    try:
        ev = await remote_session_event_service.start_console_command(
            session,
            session_id=session_id,
            command_id=body.command_id,
            correlation_id=body.correlation_id,
            payload=body.payload,
        )
        await session.commit()
        return {
            "status": "started",
            "session_id": session_id,
            "command_id": body.command_id,
            "event_cursor": ev.cursor,
        }
    except ConsoleCommandForbiddenError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.to_dict(),
        ) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/remote-sessions/{session_id}/commands/complete",
    summary="Complete an in-flight console command",
)
async def complete_console_command(
    session_id: str,
    body: ConsoleCommandCompleteRequest,
    session: Session_dep,
    _: Internal_Auth_dep,
) -> dict[str, Any]:
    ev = await remote_session_event_service.complete_console_command(
        session,
        session_id=session_id,
        command_id=body.command_id,
        exit_code=body.exit_code,
        correlation_id=body.correlation_id,
        payload=body.payload,
    )
    await session.commit()
    return {
        "status": "completed",
        "session_id": session_id,
        "command_id": body.command_id,
        "exit_code": body.exit_code,
        "event_cursor": ev.cursor,
    }


@router.post(
    "/remote-sessions/{session_id}/commands/timeout",
    summary="Record timeout for an in-flight console command",
)
async def timeout_console_command(
    session_id: str,
    body: ConsoleCommandTimeoutRequest,
    session: Session_dep,
    _: Internal_Auth_dep,
) -> dict[str, Any]:
    ev = await remote_session_event_service.timeout_console_command(
        session,
        session_id=session_id,
        command_id=body.command_id,
        correlation_id=body.correlation_id,
        payload=body.payload,
    )
    await session.commit()
    return {
        "status": "timed_out",
        "session_id": session_id,
        "command_id": body.command_id,
        "event_cursor": ev.cursor,
    }
