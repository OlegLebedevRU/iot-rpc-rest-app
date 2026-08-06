from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from core import settings
from core.diagnostics.schemas import (
    BackendErrorMessage,
    BrowserMessageAdapter,
    BrowserMessageType,
    CancelDiagnosticMessage,
    ExecDiagnosticMessage,
    StopLogMessage,
)
from core.diagnostics.service import DiagnosticService
from core.diagnostics.sessions import DiagnosticSession, registry
from core.logging_config import setup_module_logger

log = setup_module_logger(__name__, "api_diagnostics.log")
router = APIRouter(
    prefix=f"{settings.api.v1.diagnostics}",
    tags=["Diagnostics"],
)


async def _resolve_websocket_org_id(websocket: WebSocket) -> int | None:
    api_key = websocket.headers.get("x-api-key")
    if api_key and api_key in settings.api_keys:
        return settings.api_keys[api_key]

    org_id = websocket.headers.get("orgId") or websocket.headers.get("orgid")
    if org_id is None:
        return None
    try:
        return int(org_id)
    except ValueError:
        return None


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
async def diagnostics_ws(websocket: WebSocket, sn: str) -> None:
    org_id = await _resolve_websocket_org_id(websocket)
    if org_id is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    service = DiagnosticService(registry)
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
