from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from api.api_v1.api_depends import Session_dep
from core import settings
from core.crud.device_repo import DeviceRepo
from core.diagnostics.schemas import (
    BackendErrorMessage,
    BrowserMessageAdapter,
    BrowserMessageType,
    CancelDiagnosticMessage,
    ExecDiagnosticMessage,
    StopLogMessage,
)
from core.diagnostics.service import DeviceTaskDiagnosticTaskSender, DiagnosticService
from core.diagnostics.sessions import DiagnosticSession, registry
from core.logging_config import setup_module_logger

log = setup_module_logger(__name__, "api_diagnostics.log")
router = APIRouter(
    prefix=f"{settings.api.v1.diagnostics}",
    tags=["Diagnostics"],
)


async def _resolve_websocket_org_id(websocket: WebSocket) -> int | None:
    """Resolve org_id from the trusted header injected by nginx-jwt."""
    role = str(
        websocket.headers.get("X-Role")
        or websocket.headers.get("jwt-role")
        or ""
    ).lower()
    role_id = str(websocket.headers.get("X-Role-Id") or "").lower()
    user_id = str(
        websocket.headers.get("X-User-Id")
        or websocket.headers.get("jwt-sub")
        or websocket.headers.get("sub")
        or ""
    )
    is_superuser = (
        role in ("superuser", "admin", "1")
        or role_id in ("1", "superuser", "admin")
        or user_id == "1"
    )
    if not is_superuser:
        log.warning(
            "Diagnostics websocket rejected: non-superuser role=%s role_id=%s user_id=%s",
            role,
            role_id,
            user_id,
        )
        return None

    query_org_id = websocket.query_params.get("org_id")
    if query_org_id:
        try:
            return int(query_org_id)
        except ValueError:
            pass

    org_id = (
        websocket.headers.get("orgId")
        or websocket.headers.get("orgid")
        or websocket.headers.get("X-Org-Id")
        or websocket.headers.get("jwt-org")
        or websocket.headers.get("org")
    )
    if org_id is not None:
        try:
            return int(org_id)
        except ValueError:
            return None
    return None


async def _is_websocket_device_allowed(
    session: AsyncSession,
    *,
    sn: str,
    org_id: int,
) -> bool:
    device_id = await DeviceRepo.get_device_id(session=session, sn=sn, org_id=org_id)
    return device_id is not None


async def _forward_session_queue(
    websocket: WebSocket,
    session: DiagnosticSession,
) -> None:
    while True:
        message = await session.queue.get()
        await websocket.send_json(message.model_dump(mode="json"))


async def _send_error(
    websocket: WebSocket,
    error: str,
    session_id: UUID | None = None,
) -> None:
    await websocket.send_json(
        BackendErrorMessage(session_id=session_id, error=error).model_dump(mode="json")
    )


@router.websocket("/ws/devices/{sn}")
async def diagnostics_ws(websocket: WebSocket, sn: str, session: Session_dep) -> None:
    org_id = await _resolve_websocket_org_id(websocket)
    if org_id is None:
        log.warning("Diagnostics websocket rejected: missing/invalid org_id sn=%s", sn)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    if not await _is_websocket_device_allowed(session, sn=sn, org_id=org_id):
        log.warning(
            "Diagnostics websocket rejected: device not allowed sn=%s org_id=%s",
            sn,
            org_id,
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    service = DiagnosticService(
        registry,
        DeviceTaskDiagnosticTaskSender(session=session, org_id=org_id),
    )
    forwarders: dict[UUID, asyncio.Task] = {}

    async def register_forwarder(session: DiagnosticSession) -> None:
        forwarders[session.session_id] = asyncio.create_task(
            _forward_session_queue(websocket, session)
        )

    try:
        while True:
            raw_message = await websocket.receive_text()
            try:
                message = BrowserMessageAdapter.validate_json(raw_message)
            except ValidationError as exc:
                await _send_error(
                    websocket, f"invalid_message: {exc.errors()[0]['msg']}"
                )
                continue

            try:
                if message.type is BrowserMessageType.START_LOG:
                    session = await service.start_log(sn, message)  # type: ignore[arg-type]
                    await register_forwarder(session)
                    await service.emit_status(session, "started")
                elif message.type is BrowserMessageType.STOP_LOG:
                    stop_message = message
                    assert isinstance(stop_message, StopLogMessage)
                    await service.stop_log(sn, stop_message)
                    task = forwarders.pop(stop_message.session_id, None)
                    if task is not None:
                        task.cancel()
                elif message.type is BrowserMessageType.EXEC:
                    exec_message = message
                    assert isinstance(exec_message, ExecDiagnosticMessage)
                    session = await service.exec(sn, exec_message)
                    await register_forwarder(session)
                    await service.emit_status(session, "started")
                elif message.type is BrowserMessageType.CANCEL:
                    cancel_message = message
                    assert isinstance(cancel_message, CancelDiagnosticMessage)
                    await service.cancel(sn, cancel_message)
                    task = forwarders.pop(cancel_message.session_id, None)
                    if task is not None:
                        task.cancel()
            except ValueError as exc:
                await _send_error(websocket, str(exc))
    except WebSocketDisconnect:
        log.info("Diagnostics websocket disconnected: sn=%s org_id=%s", sn, org_id)
    finally:
        for session_id, task in list(forwarders.items()):
            task.cancel()
            await service.close_session(sn, session_id)
        if forwarders:
            await asyncio.gather(*forwarders.values(), return_exceptions=True)
