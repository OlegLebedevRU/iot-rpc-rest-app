from __future__ import annotations

import asyncio
import hmac
from contextlib import suppress
from datetime import datetime, timezone
from uuid import UUID

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import ValidationError

from api.internal_v1.internal_depends import (
    Internal_Auth_dep,
    Internal_Org_dep,
    Session_dep,
    is_request_superuser,
)
from core.config import settings
from core.logging_config import setup_module_logger
from core.models import db_helper
from core.remote_input.leases import lease_registry
from core.remote_input.presence import presence_registry
from core.remote_input.schemas import (
    ALLOWED_VK_CODES,
    ClickRequest,
    ClickResult,
    DeleteByOwnerRequest,
    InventoryInfo,
    KeyRequest,
    KeyResult,
    LeaseRequest,
    LeaseResponse,
    MoveRequest,
    ScopeUpgradeRequest,
    ShortcutRequest,
    ShortcutResult,
    StatusResponse,
    StreamStartRequest,
    StreamStartResponse,
    StreamStopResponse,
    WsClickResult,
    WsError,
    WsHello,
    WsInboundAdapter,
    WsKeepalive,
    WsKeepaliveResult,
    WsKeyEvent,
    WsKeyResult,
    WsLeaseRevoked,
    WsLimits,
    WsMouseClick,
    WsPointerMove,
    WsPresence,
    WsRelease,
    WsShortcutAction,
    WsShortcutResult,
)
from core.remote_input.service import remote_input_service

log = setup_module_logger(__name__, "remote_input.log")

router = APIRouter(
    prefix=settings.api.internal_v1.remote_input,
    tags=["Internal Remote Input"],
    include_in_schema=False,
)


def extract_caller_role(request_or_ws: Request | WebSocket) -> str:
    role = (
        str(
            request_or_ws.headers.get("X-Role")
            or request_or_ws.headers.get("x-role")
            or request_or_ws.headers.get("jwt-role")
            or ""
        )
        .strip()
        .lower()
    )
    role_id = (
        str(
            request_or_ws.headers.get("X-Role-Id")
            or request_or_ws.headers.get("x-role-id")
            or ""
        )
        .strip()
        .lower()
    )

    if role in ("superuser", "1") or role_id in ("1", "superuser"):
        return "superuser"
    if role in ("admin", "2") or role_id == "2":
        return "admin"
    if role in ("user", "operator", "3") or role_id == "3":
        return "user"
    if role in ("viewer", "4") or role_id == "4":
        return "viewer"
    return role or "user"


def extract_caller_user_id(request_or_ws: Request | WebSocket) -> str:
    return str(
        request_or_ws.headers.get("X-User-Id")
        or request_or_ws.headers.get("x-user-id")
        or (
            request_or_ws.query_params.get("user_id")
            if hasattr(request_or_ws, "query_params")
            else None
        )
        or request_or_ws.headers.get("jwt-sub")
        or request_or_ws.headers.get("sub")
        or ""
    ).strip()


def extract_caller_session_id(
    request_or_ws: Request | WebSocket, required: bool = True
) -> str:
    session_id = (
        request_or_ws.headers.get("X-Session-Id")
        or request_or_ws.headers.get("x-session-id")
        or (
            request_or_ws.query_params.get("session_id")
            if hasattr(request_or_ws, "query_params")
            else None
        )
        or ""
    ).strip()
    if required and not session_id:
        raise HTTPException(
            status_code=400,
            detail="Missing required X-Session-Id header or session_id query param",
        )
    return session_id


def verify_ws_internal_auth(ws: WebSocket) -> bool:
    key = (
        ws.headers.get("X-Internal-Service-Key")
        or ws.headers.get("x-internal-service-key")
        or ws.query_params.get("internal_service_key")
        or ""
    )
    if not key:
        auth_header = ws.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            key = auth_header[7:].strip()
    expected = settings.auth.internal_service_key
    if expected and key != expected:
        return False
    return True


# ── REST Endpoints ───────────────────────────────────────────────────────────


@router.get(
    "/devices/{sn}/status",
    response_model=StatusResponse,
)
async def get_device_status(
    sn: str,
    org_id: Internal_Org_dep,
    _: Internal_Auth_dep,
    session: Session_dep,
) -> StatusResponse:
    return await remote_input_service.get_status(session, sn=sn, org_id=org_id)


@router.post(
    "/devices/{sn}/lease",
    response_model=LeaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def acquire_lease(
    sn: str,
    org_id: Internal_Org_dep,
    _: Internal_Auth_dep,
    request: Request,
    session: Session_dep,
    body: LeaseRequest | None = None,
) -> LeaseResponse:
    session_id = extract_caller_session_id(request)
    caller_role = (
        body.owner_role if body and body.owner_role else None
    ) or extract_caller_role(request)
    caller_user_id = (
        (body.owner_user_id if body and body.owner_user_id else None)
        or extract_caller_user_id(request)
        or "unknown"
    )
    scope = body.scope if body else "input"
    ttl_sec = body.ttl_sec if body else None

    return await remote_input_service.acquire_lease(
        session=session,
        sn=sn,
        org_id=org_id,
        owner_user_id=caller_user_id,
        owner_role=caller_role,
        scope=scope,
        owner_session_id=session_id,
        ttl_sec=ttl_sec,
        is_superuser=is_request_superuser(request),
    )


@router.post(
    "/lease/{lease_id}/scope",
    response_model=LeaseResponse,
)
async def upgrade_lease_scope(
    lease_id: UUID,
    body: ScopeUpgradeRequest,
    org_id: Internal_Org_dep,
    _: Internal_Auth_dep,
    request: Request,
) -> LeaseResponse:
    session_id = extract_caller_session_id(request)
    caller_user_id = extract_caller_user_id(request)
    caller_role = extract_caller_role(request)

    return await remote_input_service.upgrade_scope(
        lease_id=lease_id,
        org_id=org_id,
        new_scope=body.scope,
        caller_user_id=caller_user_id,
        caller_session_id=session_id,
        caller_role=caller_role,
        is_superuser=is_request_superuser(request),
    )


@router.post(
    "/lease/{lease_id}/keepalive",
    response_model=LeaseResponse,
)
async def keepalive_lease(
    lease_id: UUID,
    org_id: Internal_Org_dep,
    _: Internal_Auth_dep,
    request: Request,
    wait_ack: bool = False,
) -> LeaseResponse:
    session_id = extract_caller_session_id(request)
    caller_user_id = extract_caller_user_id(request)

    return await remote_input_service.keepalive(
        lease_id=lease_id,
        org_id=org_id,
        caller_user_id=caller_user_id,
        caller_session_id=session_id,
        is_superuser=is_request_superuser(request),
        wait_ack=wait_ack,
    )


@router.delete(
    "/lease/{lease_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def release_lease(
    lease_id: UUID,
    org_id: Internal_Org_dep,
    _: Internal_Auth_dep,
    request: Request,
) -> Response:
    session_id = extract_caller_session_id(request)
    caller_user_id = extract_caller_user_id(request)
    request_id = request.headers.get("x-request-id")

    await remote_input_service.release(
        lease_id=lease_id,
        org_id=org_id,
        caller_user_id=caller_user_id,
        caller_session_id=session_id,
        is_superuser=is_request_superuser(request),
        channel="http",
        request_id=request_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/leases/by-owner",
)
async def delete_leases_by_owner(
    body: DeleteByOwnerRequest,
    _: Internal_Auth_dep,
) -> dict[str, int]:
    return await remote_input_service.release_by_owner(
        user_id=body.user_id,
        session_id=body.session_id,
    )


@router.get(
    "/devices/{sn}/inventory",
    response_model=InventoryInfo,
)
async def get_device_inventory(
    sn: str,
    org_id: Internal_Org_dep,
    _: Internal_Auth_dep,
    session: Session_dep,
    request: Request,
    refresh: int = 0,
) -> InventoryInfo:
    caller_user_id = extract_caller_user_id(request)
    session_id = extract_caller_session_id(request, required=False)

    return await remote_input_service.get_inventory(
        session=session,
        sn=sn,
        org_id=org_id,
        refresh=bool(refresh),
        caller_user_id=caller_user_id,
        caller_session_id=session_id,
        is_superuser=is_request_superuser(request),
    )


@router.post(
    "/lease/{lease_id}/stream/start",
    response_model=StreamStartResponse,
)
async def post_stream_start(
    lease_id: UUID,
    body: StreamStartRequest,
    org_id: Internal_Org_dep,
    _: Internal_Auth_dep,
    request: Request,
) -> StreamStartResponse:
    session_id = extract_caller_session_id(request)
    caller_user_id = extract_caller_user_id(request)

    return await remote_input_service.stream_start(
        lease_id=lease_id,
        org_id=org_id,
        mode=body.mode,
        source_id=body.source_id,
        profile=body.profile,
        caller_user_id=caller_user_id,
        caller_session_id=session_id,
        is_superuser=is_request_superuser(request),
    )


@router.post(
    "/lease/{lease_id}/stream/stop",
    response_model=StreamStopResponse,
)
async def post_stream_stop(
    lease_id: UUID,
    org_id: Internal_Org_dep,
    _: Internal_Auth_dep,
    request: Request,
) -> StreamStopResponse:
    session_id = extract_caller_session_id(request)
    caller_user_id = extract_caller_user_id(request)

    return await remote_input_service.stream_stop(
        lease_id=lease_id,
        org_id=org_id,
        caller_user_id=caller_user_id,
        caller_session_id=session_id,
        is_superuser=is_request_superuser(request),
    )


@router.post(
    "/lease/{lease_id}/pointer-move",
    status_code=status.HTTP_202_ACCEPTED,
)
@router.post(
    "/lease/{lease_id}/pointer/move",
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_pointer_move(
    lease_id: UUID,
    body: MoveRequest,
    org_id: Internal_Org_dep,
    _: Internal_Auth_dep,
    request: Request,
) -> dict[str, bool]:
    session_id = extract_caller_session_id(request)
    caller_user_id = extract_caller_user_id(request)

    return await remote_input_service.pointer_move(
        lease_id=lease_id,
        org_id=org_id,
        x=body.x,
        y=body.y,
        desktop_id=body.desktop_id,
        stream_instance_id=body.stream_instance_id,
        caller_user_id=caller_user_id,
        caller_session_id=session_id,
        is_superuser=is_request_superuser(request),
    )


@router.post(
    "/lease/{lease_id}/mouse-click",
    response_model=ClickResult,
)
@router.post(
    "/lease/{lease_id}/mouse/click",
    response_model=ClickResult,
)
async def post_mouse_click(
    lease_id: UUID,
    body: ClickRequest,
    org_id: Internal_Org_dep,
    _: Internal_Auth_dep,
    request: Request,
) -> ClickResult:
    session_id = extract_caller_session_id(request)
    caller_user_id = extract_caller_user_id(request)

    return await remote_input_service.mouse_click(
        lease_id=lease_id,
        org_id=org_id,
        x=body.x,
        y=body.y,
        button=body.button,
        client_ref=body.client_ref,
        desktop_id=body.desktop_id,
        source_id=body.source_id,
        stream_instance_id=body.stream_instance_id,
        caller_user_id=caller_user_id,
        caller_session_id=session_id,
        is_superuser=is_request_superuser(request),
    )


@router.post(
    "/lease/{lease_id}/shortcut",
    response_model=ShortcutResult,
)
@router.post(
    "/lease/{lease_id}/shortcut-action",
    response_model=ShortcutResult,
)
async def post_shortcut_action(
    lease_id: UUID,
    body: ShortcutRequest,
    org_id: Internal_Org_dep,
    _: Internal_Auth_dep,
    request: Request,
) -> ShortcutResult:
    session_id = extract_caller_session_id(request)
    caller_user_id = extract_caller_user_id(request)

    return await remote_input_service.shortcut_action(
        lease_id=lease_id,
        org_id=org_id,
        action=body.action,
        client_ref=body.client_ref,
        desktop_id=body.desktop_id,
        source_id=body.source_id,
        stream_instance_id=body.stream_instance_id,
        caller_user_id=caller_user_id,
        caller_session_id=session_id,
        is_superuser=is_request_superuser(request),
    )


@router.post(
    "/lease/{lease_id}/key",
    response_model=KeyResult,
)
async def post_key_event(
    lease_id: UUID,
    body: KeyRequest,
    org_id: Internal_Org_dep,
    _: Internal_Auth_dep,
    request: Request,
) -> KeyResult:
    session_id = extract_caller_session_id(request)
    caller_user_id = extract_caller_user_id(request)

    return await remote_input_service.key_event(
        lease_id=lease_id,
        org_id=org_id,
        kind=body.kind,
        vk=body.vk,
        text=body.text,
        client_ref=body.client_ref,
        desktop_id=body.desktop_id,
        source_id=body.source_id,
        stream_instance_id=body.stream_instance_id,
        caller_user_id=caller_user_id,
        caller_session_id=session_id,
        is_superuser=is_request_superuser(request),
    )


# ── WebSocket Endpoint ───────────────────────────────────────────────────────


@router.websocket("/ws/watch/{sn}")
async def remote_input_watch_ws(websocket: WebSocket, sn: str) -> None:
    """Internal, read-only invalidation feed for one tenant-scoped device.

    This feed uses process-local subscriptions and therefore requires one app1 worker.
    The consumer must refresh the authoritative REST snapshot after every event and
    after reconnecting; event fields are only hints, never durable state.
    """
    # This endpoint is never exposed with the development auth bypass used by REST.
    expected_key = settings.auth.internal_service_key
    supplied_key = websocket.headers.get("X-Internal-Service-Key") or ""
    if not expected_key or not hmac.compare_digest(supplied_key, expected_key):
        await websocket.close(code=4403)
        return
    raw_org = websocket.headers.get("X-Org-Id")
    try:
        org_id = int(raw_org) if raw_org else None
    except ValueError:
        org_id = None
    if org_id is None or org_id <= 0:
        await websocket.close(code=4403)
        return

    presence_queue = await presence_registry.subscribe(sn)
    stream_queue = await presence_registry.subscribe_stream(sn)
    try:
        try:
            async with db_helper.session_factory() as session:
                snapshot = await remote_input_service.get_status(
                    session, sn=sn, org_id=org_id
                )
        except HTTPException:
            await websocket.close(code=4403)
            return

        await websocket.accept()
        await asyncio.wait_for(
            websocket.send_json(
                {"type": "snapshot", "data": snapshot.model_dump(mode="json")}
            ),
            timeout=5,
        )
        # Heartbeat timestamps refresh liveness but do not change the browser's
        # authoritative status view. Keep every other field, including desktop
        # availability and stream identity, in the comparison.
        last_agent_state = snapshot.agent.model_dump(
            mode="json", exclude={"last_seen_at"}
        )
        while True:
            # The receive task exists solely to detect disconnects and reject writes.
            tasks = [
                asyncio.create_task(presence_queue.get()),
                asyncio.create_task(stream_queue.get()),
                asyncio.create_task(websocket.receive_text()),
            ]
            try:
                done, pending = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
                for task in pending:
                    with suppress(asyncio.CancelledError):
                        await task
                if tasks[2] in done:
                    try:
                        tasks[2].result()
                    except WebSocketDisconnect:
                        return
                    # No command namespace is accepted on this channel.
                    await websocket.close(code=4403)
                    return
                if presence_queue.qsize() + stream_queue.qsize() > 100:
                    await websocket.close(code=1013)
                    return
                for task, kind in ((tasks[0], "presence"), (tasks[1], "stream")):
                    if task in done:
                        event = task.result()
                        if kind == "presence":
                            agent_state = event.model_dump(
                                mode="json", exclude={"last_seen_at"}
                            )
                            if agent_state == last_agent_state:
                                continue
                            last_agent_state = agent_state
                        await asyncio.wait_for(
                            websocket.send_json(
                                {
                                    "type": "invalidate",
                                    "kind": kind,
                                    "online": (
                                        event.online if kind == "presence" else None
                                    ),
                                    "state": event.state if kind == "stream" else None,
                                    "reason": (
                                        event.reason if kind == "stream" else None
                                    ),
                                    "stream_instance_id": (
                                        str(event.stream_instance_id)
                                        if kind == "stream" and event.stream_instance_id
                                        else None
                                    ),
                                    "timestamp": (
                                        event.timestamp if kind == "stream" else None
                                    )
                                    or datetime.now(timezone.utc).isoformat(),
                                }
                            ),
                            timeout=5,
                        )
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                for task in tasks:
                    with suppress(asyncio.CancelledError, WebSocketDisconnect):
                        await task
    except WebSocketDisconnect, TimeoutError:
        pass
    finally:
        await presence_registry.unsubscribe_stream(sn, stream_queue)
        await presence_registry.unsubscribe(sn, presence_queue)


@router.websocket("/ws/lease/{lease_id}")
async def remote_input_ws(
    websocket: WebSocket,
    lease_id: UUID,
) -> None:
    # 1. Internal Auth Verification
    if not verify_ws_internal_auth(websocket):
        log.warning("Rejecting remote input WS: invalid internal service key")
        await websocket.close(code=4403)
        return

    # 2. Lease Lookup & Expiry Check
    lease = await lease_registry.get(lease_id)
    if lease is None or not lease.is_active():
        log.warning(
            "Rejecting remote input WS: lease %s not found or inactive", lease_id
        )
        await websocket.close(code=4404)
        return

    caller_role = extract_caller_role(websocket)
    caller_user_id = extract_caller_user_id(websocket)
    caller_session_id = extract_caller_session_id(websocket, required=False)
    is_su = is_request_superuser(websocket)

    # 3. Caller Role & Scope Verification
    if not is_su:
        if caller_role in ("viewer", "4") and lease.scope != "view":
            log.warning(
                "Rejecting remote input WS: viewer role not allowed for scope %s",
                lease.scope,
            )
            await websocket.close(code=4403)
            return

    # 4. Tenant & User Verification
    raw_org = (
        websocket.headers.get("X-Org-Id")
        or websocket.headers.get("x-org-id")
        or websocket.query_params.get("org_id")
    )
    try:
        org_id = int(raw_org) if raw_org else None
    except ValueError:
        org_id = None

    if not is_su:
        if org_id is None or org_id != lease.org_id:
            log.warning(
                "Rejecting remote input WS: org_id mismatch header=%s lease=%s",
                org_id,
                lease.org_id,
            )
            await websocket.close(code=4403)
            return

        if caller_user_id and caller_user_id != lease.owner_user_id:
            log.warning(
                "Rejecting remote input WS: user mismatch caller=%s owner=%s",
                caller_user_id,
                lease.owner_user_id,
            )
            await websocket.close(code=4403)
            return

        if caller_session_id and caller_session_id != lease.owner_session_id:
            log.warning(
                "Rejecting remote input WS: session mismatch caller=%s owner=%s",
                caller_session_id,
                lease.owner_session_id,
            )
            await websocket.close(code=4403)
            return

    # 5. Single WS connection per active lease
    connected = await lease_registry.mark_ws_connected(lease_id)
    if not connected:
        log.warning(
            "Rejecting remote input WS: lease %s already has active WS connection",
            lease_id,
        )
        await websocket.close(code=4409)
        return

    await websocket.accept()

    # Outgoing message queue for thread-safe websocket.send_json
    outgoing_queue: asyncio.Queue[dict | None] = asyncio.Queue()
    move_queue: asyncio.Queue[WsPointerMove] = asyncio.Queue(maxsize=1)

    presence_queue = await presence_registry.subscribe(lease.sn)
    stream_queue = await presence_registry.subscribe_stream(lease.sn)
    revocation_queue = await lease_registry.subscribe_revocation(lease_id)

    async def sender_worker() -> None:
        while True:
            item = await outgoing_queue.get()
            if item is None:
                outgoing_queue.task_done()
                break
            try:
                await websocket.send_json(item)
            except Exception as exc:
                log.debug("Sender worker failed to send WS message: %s", exc)
                outgoing_queue.task_done()
                break
            finally:
                outgoing_queue.task_done()

    async def pointer_move_worker() -> None:
        while True:
            msg = await move_queue.get()
            try:
                await remote_input_service.pointer_move(
                    lease_id=lease_id,
                    org_id=lease.org_id,
                    x=msg.x,
                    y=msg.y,
                    desktop_id=msg.desktop_id,
                    source_id=msg.source_id,
                    stream_instance_id=msg.stream_instance_id,
                    caller_user_id=lease.owner_user_id,
                    caller_session_id=lease.owner_session_id,
                    is_superuser=True,
                    skip_rate_limit=False,
                )
            except HTTPException as exc:
                code_str = (
                    "rate_limited"
                    if exc.status_code == 429
                    else str(exc.detail) if isinstance(exc.detail, str) else "error"
                )
                await outgoing_queue.put(
                    WsError(
                        code=code_str,
                        message=str(exc.detail),
                    ).model_dump(mode="json")
                )
            except Exception as exc:
                log.warning("Pointer move worker error: %s", exc)
            finally:
                move_queue.task_done()

    async def presence_worker() -> None:
        while True:
            view = await presence_queue.get()
            try:
                ws_presence = WsPresence(
                    online=view.online,
                    desktop_available=view.desktop_available,
                    session_id=view.session_id,
                    screen=view.screen,
                    inventory=view.inventory,
                    stream=view.stream,
                    last_seen_at=view.last_seen_at,
                    stale=view.stale,
                )
                await outgoing_queue.put(ws_presence.model_dump(mode="json"))
            finally:
                presence_queue.task_done()

    async def stream_worker() -> None:
        while True:
            st_evt = await stream_queue.get()
            try:
                await outgoing_queue.put(st_evt.model_dump(mode="json"))
            finally:
                stream_queue.task_done()

    async def revocation_worker() -> None:
        reason = await revocation_queue.get()
        try:
            await outgoing_queue.put(
                WsLeaseRevoked(reason=reason).model_dump(mode="json")
            )
            await outgoing_queue.put(None)
        finally:
            revocation_queue.task_done()

    sender_task = asyncio.create_task(sender_worker())
    move_task = asyncio.create_task(pointer_move_worker())
    presence_task = asyncio.create_task(presence_worker())
    stream_task = asyncio.create_task(stream_worker())
    revocation_task = asyncio.create_task(revocation_worker())

    # Send WsHello initial message
    hello = WsHello(
        lease_id=lease.lease_id,
        sn=lease.sn,
        expires_at=lease.expires_at,
        keepalive_sec=settings.remote_input.lease_keepalive_sec,
        limits=WsLimits(
            move_per_sec=settings.remote_input.move_rate_per_sec,
            click_per_sec=settings.remote_input.click_rate_per_sec,
        ),
    )
    await outgoing_queue.put(hello.model_dump(mode="json"))

    initial_presence = await presence_registry.get(lease.sn)
    pres_msg = WsPresence(
        online=initial_presence.online,
        desktop_available=initial_presence.desktop_available,
        session_id=initial_presence.session_id,
        screen=initial_presence.screen,
        inventory=initial_presence.inventory,
        stream=initial_presence.stream,
        last_seen_at=initial_presence.last_seen_at,
        stale=initial_presence.stale,
    )
    await outgoing_queue.put(pres_msg.model_dump(mode="json"))

    try:
        while True:
            raw_text = await websocket.receive_text()
            if len(raw_text) > settings.remote_input.max_command_payload_bytes:
                await outgoing_queue.put(
                    WsError(
                        code="payload_too_large",
                        message="Payload exceeds maximum allowed size",
                    ).model_dump(mode="json")
                )
                continue

            try:
                msg = WsInboundAdapter.validate_json(raw_text)
            except ValidationError as exc:
                await outgoing_queue.put(
                    WsError(
                        code="invalid_message",
                        message=f"Validation failed: {exc}",
                    ).model_dump(mode="json")
                )
                continue

            # Scope view check: view is read-only
            if lease.scope == "view":
                if isinstance(msg, WsKeepalive):
                    resp = await remote_input_service.keepalive(
                        lease_id=lease_id,
                        org_id=lease.org_id,
                        caller_user_id=lease.owner_user_id,
                        caller_session_id=lease.owner_session_id,
                        is_superuser=True,
                    )
                    await outgoing_queue.put(
                        WsKeepaliveResult(
                            lease_id=resp.lease_id,
                            expires_at=resp.expires_at,
                            renew_status=resp.renew_status,
                            terminal_healthy=resp.terminal_healthy,
                            applied_deadline_ms=resp.applied_deadline_ms,
                        ).model_dump(mode="json")
                    )
                elif isinstance(msg, WsRelease):
                    await remote_input_service.release(
                        lease_id=lease_id,
                        org_id=lease.org_id,
                        caller_user_id=lease.owner_user_id,
                        caller_session_id=lease.owner_session_id,
                        is_superuser=True,
                        channel="ws",
                    )
                    break
                else:
                    await outgoing_queue.put(
                        WsError(
                            code="scope_not_allowed",
                            message="Input commands not allowed in view scope",
                        ).model_dump(mode="json")
                    )
                continue

            if isinstance(msg, WsPointerMove):
                if lease.scope != "input":
                    await outgoing_queue.put(
                        WsError(
                            code="scope_not_allowed",
                            message="Pointer move not allowed for non-input scope",
                        ).model_dump(mode="json")
                    )
                    continue

                if lease.stream_mode is None and lease.scope in ("stream", "input"):
                    lease.stream_mode = "desktop"

                if lease.stream_mode != "desktop":
                    await outgoing_queue.put(
                        WsError(
                            code="mode_conflict",
                            message="Pointer move only allowed in desktop mode",
                        ).model_dump(mode="json")
                    )
                    continue

                if move_queue.full():
                    try:
                        move_queue.get_nowait()
                        move_queue.task_done()
                    except asyncio.QueueEmpty:
                        pass
                await move_queue.put(msg)

            elif isinstance(msg, WsMouseClick):
                if lease.scope != "input":
                    await outgoing_queue.put(
                        WsError(
                            code="scope_not_allowed",
                            message="Mouse click not allowed for non-input scope",
                            client_ref=msg.client_ref,
                        ).model_dump(mode="json")
                    )
                    continue

                if lease.stream_mode is None and lease.scope in ("stream", "input"):
                    lease.stream_mode = "desktop"

                if lease.stream_mode != "desktop":
                    await outgoing_queue.put(
                        WsError(
                            code="mode_conflict",
                            message="Mouse click only allowed in desktop mode",
                            client_ref=msg.client_ref,
                        ).model_dump(mode="json")
                    )
                    continue

                try:
                    click_res = await remote_input_service.mouse_click(
                        lease_id=lease_id,
                        org_id=lease.org_id,
                        x=msg.x,
                        y=msg.y,
                        button=msg.button,
                        client_ref=msg.client_ref,
                        desktop_id=msg.desktop_id,
                        source_id=msg.source_id,
                        stream_instance_id=msg.stream_instance_id,
                        caller_user_id=lease.owner_user_id,
                        caller_session_id=lease.owner_session_id,
                        is_superuser=True,
                        skip_rate_limit=False,
                    )
                    ws_res = WsClickResult(
                        command_id=click_res.command_id,
                        client_ref=click_res.client_ref,
                        result=click_res.result,
                        code=click_res.code,
                        message=click_res.message,
                        latency_ms=click_res.latency_ms,
                    )
                    await outgoing_queue.put(ws_res.model_dump(mode="json"))
                except HTTPException as exc:
                    code_str = (
                        "rate_limited"
                        if exc.status_code == 429
                        else str(exc.detail) if isinstance(exc.detail, str) else "error"
                    )
                    await outgoing_queue.put(
                        WsError(
                            code=code_str,
                            message=str(exc.detail),
                            client_ref=msg.client_ref,
                        ).model_dump(mode="json")
                    )

            elif isinstance(msg, WsShortcutAction):
                if lease.scope != "input":
                    await outgoing_queue.put(
                        WsError(
                            code="scope_not_allowed",
                            message="Shortcut action not allowed for non-input scope",
                            client_ref=msg.client_ref,
                        ).model_dump(mode="json")
                    )
                    continue

                if lease.stream_mode is None and lease.scope in ("stream", "input"):
                    lease.stream_mode = "desktop"

                if lease.stream_mode != "desktop":
                    await outgoing_queue.put(
                        WsError(
                            code="mode_conflict",
                            message="Shortcut action only allowed in desktop mode",
                            client_ref=msg.client_ref,
                        ).model_dump(mode="json")
                    )
                    continue

                try:
                    sc_res = await remote_input_service.shortcut_action(
                        lease_id=lease_id,
                        org_id=lease.org_id,
                        action=msg.action,
                        client_ref=msg.client_ref,
                        desktop_id=msg.desktop_id,
                        source_id=msg.source_id,
                        stream_instance_id=msg.stream_instance_id,
                        caller_user_id=lease.owner_user_id,
                        caller_session_id=lease.owner_session_id,
                        is_superuser=True,
                        skip_rate_limit=False,
                    )
                    ws_sc_res = WsShortcutResult(
                        command_id=sc_res.command_id,
                        client_ref=sc_res.client_ref,
                        result=sc_res.result,
                        code=sc_res.code,
                        message=sc_res.message,
                        latency_ms=sc_res.latency_ms,
                    )
                    await outgoing_queue.put(ws_sc_res.model_dump(mode="json"))
                except HTTPException as exc:
                    code_str = (
                        "rate_limited"
                        if exc.status_code == 429
                        else str(exc.detail) if isinstance(exc.detail, str) else "error"
                    )
                    await outgoing_queue.put(
                        WsError(
                            code=code_str,
                            message=str(exc.detail),
                            client_ref=msg.client_ref,
                        ).model_dump(mode="json")
                    )

            elif isinstance(msg, WsKeyEvent):
                if lease.scope != "input":
                    await outgoing_queue.put(
                        WsError(
                            code="scope_not_allowed",
                            message="Key event not allowed for non-input scope",
                            client_ref=msg.client_ref,
                        ).model_dump(mode="json")
                    )
                    continue

                if lease.stream_mode is None and lease.scope in ("stream", "input"):
                    lease.stream_mode = "desktop"

                if lease.stream_mode != "desktop":
                    await outgoing_queue.put(
                        WsError(
                            code="mode_conflict",
                            message="Key event only allowed in desktop mode",
                            client_ref=msg.client_ref,
                        ).model_dump(mode="json")
                    )
                    continue

                if msg.vk not in ALLOWED_VK_CODES:
                    await outgoing_queue.put(
                        WsError(
                            code="vk_not_allowed",
                            message=f"Virtual key code {msg.vk} is not in whitelist",
                            client_ref=msg.client_ref,
                        ).model_dump(mode="json")
                    )
                    continue

                try:
                    key_res = await remote_input_service.key_event(
                        lease_id=lease_id,
                        org_id=lease.org_id,
                        kind=msg.kind,
                        vk=msg.vk,
                        text=msg.text,
                        client_ref=msg.client_ref,
                        desktop_id=msg.desktop_id,
                        source_id=msg.source_id,
                        stream_instance_id=msg.stream_instance_id,
                        caller_user_id=lease.owner_user_id,
                        caller_session_id=lease.owner_session_id,
                        is_superuser=True,
                        skip_rate_limit=False,
                    )
                    ws_k_res = WsKeyResult(
                        command_id=key_res.command_id,
                        client_ref=key_res.client_ref,
                        result=key_res.result,
                        code=key_res.code,
                        message=key_res.message,
                        latency_ms=key_res.latency_ms,
                    )
                    await outgoing_queue.put(ws_k_res.model_dump(mode="json"))
                except HTTPException as exc:
                    code_str = (
                        "rate_limited"
                        if exc.status_code == 429
                        else str(exc.detail) if isinstance(exc.detail, str) else "error"
                    )
                    await outgoing_queue.put(
                        WsError(
                            code=code_str,
                            message=str(exc.detail),
                            client_ref=msg.client_ref,
                        ).model_dump(mode="json")
                    )

            elif isinstance(msg, WsKeepalive):
                resp = await remote_input_service.keepalive(
                    lease_id=lease_id,
                    org_id=lease.org_id,
                    caller_user_id=lease.owner_user_id,
                    caller_session_id=lease.owner_session_id,
                    is_superuser=True,
                )
                await outgoing_queue.put(
                    WsKeepaliveResult(
                        lease_id=resp.lease_id,
                        expires_at=resp.expires_at,
                        renew_status=resp.renew_status,
                        terminal_healthy=resp.terminal_healthy,
                        applied_deadline_ms=resp.applied_deadline_ms,
                    ).model_dump(mode="json")
                )

            elif isinstance(msg, WsRelease):
                await remote_input_service.release(
                    lease_id=lease_id,
                    org_id=lease.org_id,
                    caller_user_id=lease.owner_user_id,
                    caller_session_id=lease.owner_session_id,
                    is_superuser=True,
                    channel="ws",
                )
                break

    except WebSocketDisconnect:
        log.info("Remote input WS disconnected: lease_id=%s", lease_id)
    except Exception as exc:
        log.warning("Remote input WS error for lease_id=%s: %s", lease_id, exc)
    finally:
        # Give pending outgoing messages a moment to dispatch
        try:
            await asyncio.sleep(0.01)
        except Exception:
            pass

        for t in (
            sender_task,
            move_task,
            presence_task,
            stream_task,
            revocation_task,
        ):
            t.cancel()

        await presence_registry.unsubscribe_stream(lease.sn, stream_queue)
        await presence_registry.unsubscribe(lease.sn, presence_queue)
        await lease_registry.unsubscribe_revocation(lease_id, revocation_queue)
        await lease_registry.mark_ws_disconnected(lease_id)

        try:
            await websocket.close()
        except Exception:
            pass
