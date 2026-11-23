from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from api.internal_v1.internal_depends import Session_dep
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
from core.remote_input.leases import lease_registry

log = setup_module_logger(__name__, "api_internal_diagnostics.log")
router = APIRouter(
    prefix=settings.api.internal_v1.diagnostics,
    tags=["Internal Diagnostics"],
    include_in_schema=False,
)

active_diagnostics_ws: dict[str, WebSocket] = {}


async def close_diagnostics_ws_for_sn(sn: str, reason: str = "lease_revoked") -> None:
    ws = active_diagnostics_ws.pop(sn, None)
    if ws is not None:
        try:
            await ws.close(code=4409, reason=reason)
        except Exception:
            pass


async def _resolve_websocket_org_id(websocket: WebSocket) -> int | None:
    """Accept only the internal gateway with a successful MenuBuilder decision."""
    secret = settings.auth.internal_service_key
    supplied = websocket.headers.get("X-Internal-Service-Key", "")
    if not secret or not secrets.compare_digest(secret.encode(), supplied.encode()):
        return None
    try:
        org = int(websocket.headers.get("X-Console-Org", ""))
    except ValueError:
        return None
    return org if org > 0 else None


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
    forwarders: dict[UUID, asyncio.Task] | None = None,
) -> None:
    try:
        while True:
            remaining = (session.expires_at - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                await _send_error(
                    websocket, "session_expired", UUID(str(session.session_id))
                )
                break
            try:
                message = await asyncio.wait_for(session.queue.get(), timeout=remaining)
            except TimeoutError:
                await _send_error(
                    websocket, "session_expired", UUID(str(session.session_id))
                )
                break
            try:
                await asyncio.wait_for(
                    websocket.send_json(message.model_dump(mode="json")),
                    timeout=min(5.0, remaining),
                )
                if getattr(message, "eof", False):
                    break
            finally:
                session.queue.task_done()
    finally:
        await registry.remove(session.sn, session.session_id)
        if forwarders is not None:
            forwarders.pop(UUID(str(session.session_id)), None)


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

    try:
        grant_expiry = int(websocket.headers.get("X-Console-Expires", ""))
    except ValueError:
        grant_expiry = 0
    if grant_expiry <= datetime.now(UTC).timestamp():
        await websocket.close(code=4401, reason="admission_expired")
        return
    caller_user_id = websocket.headers.get("X-Console-User")
    caller_session_id = websocket.headers.get("X-Console-Session")
    raw_id = websocket.query_params.get("lease_id")
    if not raw_id:
        await websocket.close(code=4409, reason="lease_required")
        return
    try:
        lease_id = UUID(raw_id)
    except ValueError:
        await websocket.close(code=4409, reason="invalid_lease_id")
        return
    lease = await lease_registry.get(lease_id)
    if (
        lease is None
        or not lease.is_active()
        or lease.sn != sn
        or lease.org_id != org_id
    ):
        await websocket.close(code=4409, reason="lease_inactive")
        return
    if lease.scope != "console":
        await websocket.close(code=4409, reason="scope_mismatch")
        return
    if not caller_user_id or lease.owner_user_id != caller_user_id:
        await websocket.close(code=4409, reason="lease_not_owner")
        return
    if not caller_session_id or lease.owner_session_id != caller_session_id:
        await websocket.close(code=4409, reason="lease_session_mismatch")
        return

    await websocket.accept()
    active_diagnostics_ws[sn] = websocket
    await lease_registry.mark_ws_connected(lease.lease_id)

    service = DiagnosticService(
        registry,
        DeviceTaskDiagnosticTaskSender(session=session, org_id=org_id),
    )
    forwarders: dict[UUID, asyncio.Task] = {}

    async def register_forwarder(diag_sess: DiagnosticSession) -> None:
        forwarders[UUID(str(diag_sess.session_id))] = asyncio.create_task(
            _forward_session_queue(websocket, diag_sess, forwarders)
        )

    try:
        while True:
            remaining = grant_expiry - datetime.now(UTC).timestamp()
            if remaining <= 0:
                await websocket.close(code=4401, reason="admission_expired")
                break
            try:
                raw_message = await asyncio.wait_for(
                    websocket.receive_text(), remaining
                )
            except TimeoutError:
                await websocket.close(code=4401, reason="admission_expired")
                break
            current = await lease_registry.get(lease.lease_id)
            if current is None or not current.is_active() or current.scope != "console":
                await websocket.close(code=4409, reason="lease_inactive")
                break
            try:
                message = BrowserMessageAdapter.validate_json(raw_message)
            except ValidationError as exc:
                await _send_error(
                    websocket, f"invalid_message: {exc.errors()[0]['msg']}"
                )
                continue

            try:
                if message.type is BrowserMessageType.START_LOG:
                    diag_sess = await service.start_log(sn, message)  # type: ignore[arg-type]
                    await register_forwarder(diag_sess)
                elif message.type is BrowserMessageType.STOP_LOG:
                    stop_message = message
                    assert isinstance(stop_message, StopLogMessage)
                    await service.stop_log(sn, stop_message)
                    task = forwarders.pop(UUID(str(stop_message.session_id)), None)
                    if task is not None:
                        task.cancel()
                elif message.type is BrowserMessageType.EXEC:
                    exec_message = message
                    assert isinstance(exec_message, ExecDiagnosticMessage)
                    diag_sess = await service.exec(sn, exec_message)
                    await register_forwarder(diag_sess)
                elif message.type is BrowserMessageType.CANCEL:
                    cancel_message = message
                    assert isinstance(cancel_message, CancelDiagnosticMessage)
                    await service.cancel(sn, cancel_message)
                    # Preserve the forwarder until actual terminal EOF/timeout.
            except ValueError as exc:
                await _send_error(websocket, str(exc))
    except WebSocketDisconnect:
        log.info("Diagnostics websocket disconnected: sn=%s org_id=%s", sn, org_id)
    finally:
        active_diagnostics_ws.pop(sn, None)
        await lease_registry.mark_ws_disconnected(lease.lease_id)
        active_sessions = list(forwarders.items())
        forwarders.clear()
        for session_id, task in active_sessions:
            task.cancel()
            await service.close_session(sn, session_id)
        if active_sessions:
            await asyncio.gather(
                *(task for _, task in active_sessions),
                return_exceptions=True,
            )
