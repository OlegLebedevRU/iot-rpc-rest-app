from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import (
    APIRouter,
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
from core.remote_input.leases import lease_registry
from core.remote_input.pending import pending_registry
from core.remote_input.presence import presence_registry
from core.remote_input.rate_limit import rate_limiter
from core.remote_input.schemas import (
    ClickRequest,
    ClickResult,
    LeaseRequest,
    LeaseResponse,
    MoveRequest,
    StatusResponse,
    WsClickResult,
    WsError,
    WsHello,
    WsInboundAdapter,
    WsKeepalive,
    WsLeaseRevoked,
    WsLimits,
    WsMouseClick,
    WsPointerMove,
    WsPresence,
    WsRelease,
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
        or request_or_ws.headers.get("jwt-sub")
        or request_or_ws.headers.get("sub")
        or ""
    ).strip()


def verify_ws_internal_auth(ws: WebSocket) -> bool:
    key = (
        ws.headers.get("X-Internal-Service-Key")
        or ws.headers.get("x-internal-service-key")
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
    caller_role = (
        body.owner_role if body and body.owner_role else None
    ) or extract_caller_role(request)
    caller_user_id = (
        (body.owner_user_id if body and body.owner_user_id else None)
        or extract_caller_user_id(request)
        or "unknown"
    )

    return await remote_input_service.acquire_lease(
        session=session,
        sn=sn,
        org_id=org_id,
        owner_user_id=caller_user_id,
        owner_role=caller_role,
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
) -> LeaseResponse:
    return await remote_input_service.keepalive(
        lease_id=lease_id,
        org_id=org_id,
        is_superuser=is_request_superuser(request),
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
    await remote_input_service.release(
        lease_id=lease_id,
        org_id=org_id,
        is_superuser=is_request_superuser(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/lease/{lease_id}/pointer-move",
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_pointer_move(
    lease_id: UUID,
    body: MoveRequest,
    org_id: Internal_Org_dep,
    _: Internal_Auth_dep,
    request: Request,
) -> dict[str, bool]:
    return await remote_input_service.pointer_move(
        lease_id=lease_id,
        org_id=org_id,
        x=body.x,
        y=body.y,
        is_superuser=is_request_superuser(request),
    )


@router.post(
    "/lease/{lease_id}/mouse-click",
    response_model=ClickResult,
)
async def post_mouse_click(
    lease_id: UUID,
    body: ClickRequest,
    org_id: Internal_Org_dep,
    _: Internal_Auth_dep,
    request: Request,
) -> ClickResult:
    return await remote_input_service.mouse_click(
        lease_id=lease_id,
        org_id=org_id,
        x=body.x,
        y=body.y,
        button=body.button,
        client_ref=body.client_ref,
        is_superuser=is_request_superuser(request),
    )


# ── WebSocket Endpoint ───────────────────────────────────────────────────────


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

    # 2. Caller Role Verification
    caller_role = extract_caller_role(websocket)
    is_su = is_request_superuser(websocket)
    if (caller_role in ("viewer", "4")) and not is_su:
        log.warning(
            "Rejecting remote input WS: caller role '%s' not allowed", caller_role
        )
        await websocket.close(code=4403)
        return

    # 3. Lease Lookup & Expiry Check
    lease = await lease_registry.get(lease_id)
    if lease is None or not lease.is_active():
        log.warning(
            "Rejecting remote input WS: lease %s not found or inactive", lease_id
        )
        await websocket.close(code=4404)
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

        caller_user_id = extract_caller_user_id(websocket)
        if caller_user_id and caller_user_id != lease.owner_user_id:
            log.warning(
                "Rejecting remote input WS: user mismatch caller=%s owner=%s",
                caller_user_id,
                lease.owner_user_id,
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
    revocation_queue = await lease_registry.subscribe_revocation(lease_id)

    async def sender_worker() -> None:
        while True:
            item = await outgoing_queue.get()
            if item is None:
                outgoing_queue.task_done()
                break
            try:
                await websocket.send_json(item)
            except Exception as e:
                log.debug("WS send_json error: %s", e)
                outgoing_queue.task_done()
                break
            outgoing_queue.task_done()

    async def move_worker() -> None:
        while True:
            cmd = await move_queue.get()
            try:
                await remote_input_service.pointer_move(
                    lease_id=lease.lease_id,
                    org_id=lease.org_id,
                    x=cmd.x,
                    y=cmd.y,
                    is_superuser=True,
                    skip_rate_limit=True,
                )
            except Exception as exc:
                log.debug("WS move_worker send error: %s", exc)
            move_queue.task_done()

    async def presence_worker() -> None:
        while True:
            agent_view = await presence_queue.get()
            msg = WsPresence(
                online=agent_view.online,
                desktop_available=agent_view.desktop_available,
                screen=agent_view.screen,
                last_seen_at=agent_view.last_seen_at,
                stale=agent_view.stale,
            ).model_dump(mode="json")
            await outgoing_queue.put(msg)
            presence_queue.task_done()

    async def revocation_worker() -> None:
        if revocation_queue is None:
            return
        reason = await revocation_queue.get()
        msg = WsLeaseRevoked(reason=reason).model_dump(mode="json")
        await outgoing_queue.put(msg)
        revocation_queue.task_done()
        # Wait a moment for sender to deliver and close WS
        await asyncio.sleep(0.05)
        try:
            await websocket.close(code=1000)
        except Exception:
            pass

    async def execute_ws_click(click_cmd: WsMouseClick) -> None:
        allowed = await rate_limiter.check_rate_limit(
            lease_id, "mouse_click", settings.remote_input.click_rate_per_sec
        )
        if not allowed:
            err = WsError(
                code="rate_limited",
                message="Click rate limit exceeded",
                client_ref=click_cmd.client_ref,
            ).model_dump(mode="json")
            await outgoing_queue.put(err)
            return

        res = await remote_input_service.mouse_click(
            lease_id=lease.lease_id,
            org_id=lease.org_id,
            x=click_cmd.x,
            y=click_cmd.y,
            button=click_cmd.button,
            client_ref=click_cmd.client_ref,
            is_superuser=True,
            skip_rate_limit=True,
        )

        out_msg = WsClickResult(
            command_id=res.command_id,
            client_ref=click_cmd.client_ref,
            result=res.result,
            code=res.code,
            message=res.message,
            latency_ms=res.latency_ms,
        ).model_dump(mode="json")
        await outgoing_queue.put(out_msg)

    # 6. Send Initial hello and presence
    hello = WsHello(
        lease_id=lease.lease_id,
        sn=lease.sn,
        expires_at=lease.expires_at,
        keepalive_sec=settings.remote_input.lease_keepalive_sec,
        limits=WsLimits(
            move_per_sec=settings.remote_input.move_rate_per_sec,
            click_per_sec=settings.remote_input.click_rate_per_sec,
        ),
    ).model_dump(mode="json")
    await outgoing_queue.put(hello)

    initial_presence = await presence_registry.get(lease.sn)
    pres_msg = WsPresence(
        online=initial_presence.online,
        desktop_available=initial_presence.desktop_available,
        screen=initial_presence.screen,
        last_seen_at=initial_presence.last_seen_at,
        stale=initial_presence.stale,
    ).model_dump(mode="json")
    await outgoing_queue.put(pres_msg)

    tasks = [
        asyncio.create_task(sender_worker(), name="ws-sender"),
        asyncio.create_task(move_worker(), name="ws-move"),
        asyncio.create_task(presence_worker(), name="ws-presence"),
        asyncio.create_task(revocation_worker(), name="ws-revocation"),
    ]

    try:
        while True:
            message_text = await websocket.receive_text()
            if (
                len(message_text.encode("utf-8"))
                > settings.remote_input.max_inbound_payload_bytes
            ):
                await outgoing_queue.put(
                    WsError(
                        code="payload_too_large",
                        message="Payload size exceeds limit",
                    ).model_dump(mode="json")
                )
                continue

            # Any incoming message is implicit keepalive
            await lease_registry.touch(lease_id, settings.remote_input.lease_ttl_sec)

            try:
                cmd = WsInboundAdapter.validate_json(message_text)
            except (ValidationError, ValueError) as err:
                await outgoing_queue.put(
                    WsError(
                        code="invalid_message",
                        message=str(err),
                    ).model_dump(mode="json")
                )
                continue

            if isinstance(cmd, WsPointerMove):
                allowed = await rate_limiter.check_rate_limit(
                    lease_id,
                    "pointer_move",
                    settings.remote_input.move_rate_per_sec,
                )
                if not allowed:
                    await outgoing_queue.put(
                        WsError(
                            code="rate_limited",
                            message="Pointer move rate limit exceeded",
                        ).model_dump(mode="json")
                    )
                    continue

                # Latest-wins: if queue is full, drop previous move
                if move_queue.full():
                    try:
                        move_queue.get_nowait()
                        move_queue.task_done()
                    except asyncio.QueueEmpty, ValueError:
                        pass
                move_queue.put_nowait(cmd)

            elif isinstance(cmd, WsMouseClick):
                # Run concurrently so clicks don't block pointer moves
                asyncio.create_task(execute_ws_click(cmd))

            elif isinstance(cmd, WsKeepalive):
                pass  # Already touched above

            elif isinstance(cmd, WsRelease):
                await remote_input_service.release(
                    lease_id=lease.lease_id,
                    org_id=lease.org_id,
                    is_superuser=True,
                )
                break

    except WebSocketDisconnect:
        log.info("Remote input WS disconnected for lease=%s", lease_id)
    except Exception as exc:
        log.warning("Remote input WS exception for lease=%s: %s", lease_id, exc)
    finally:
        # Allow sender worker to flush outgoing queue
        try:
            await asyncio.wait_for(outgoing_queue.join(), timeout=0.5)
        except Exception:
            pass

        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        await lease_registry.mark_ws_disconnected(lease_id)
        await presence_registry.unsubscribe(lease.sn, presence_queue)
        if revocation_queue is not None:
            await lease_registry.unsubscribe_revocation(lease_id, revocation_queue)

        # On WS disconnect: release lease and cancel pending
        await lease_registry.revoke(lease_id, reason="released")
        await pending_registry.cancel_for_lease(lease_id, reason="released")
        await rate_limiter.cleanup_lease(lease_id)
