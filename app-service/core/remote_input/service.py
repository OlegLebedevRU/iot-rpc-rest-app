from __future__ import annotations

import asyncio
import json
import time
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.crud.device_repo import DeviceRepo
from core.logging_config import setup_module_logger
from core.remote_input.leases import (
    Lease,
    LeaseConflictError,
    LeaseRegistryProtocol,
    lease_registry,
    mask_user_id,
)
from core.remote_input.pending import (
    PendingCommandRegistryProtocol,
    pending_registry,
)
from core.remote_input.presence import (
    PresenceRegistryProtocol,
    presence_registry,
)
from core.remote_input.publisher import send_ctl_command
from core.remote_input.rate_limit import RateLimiter, rate_limiter
from core.remote_input.schemas import (
    ALLOWED_VK_CODES,
    ClickResult,
    InventoryGetCommand,
    InventoryInfo,
    KeyEventCommand,
    KeyResult,
    LeaseResponse,
    LeaseScope,
    LeaseStatusView,
    MouseClickCommand,
    PointerMoveCommand,
    StatusResponse,
    StreamStartCommand,
    StreamStartResponse,
    StreamStopCommand,
    StreamStopResponse,
)

log = setup_module_logger(__name__, "remote_input.log")


def log_audit(
    event: str,
    *,
    lease_id: UUID | None = None,
    org_id: int | None = None,
    device_id: int | None = None,
    sn: str | None = None,
    cmd_type: str | None = None,
    result: str | None = None,
    code: str | None = None,
    latency_ms: int | None = None,
    owner_user_id: str | None = None,
) -> None:
    data = {
        "event": event,
        "ts": time.time(),
        "lease_id": str(lease_id) if lease_id else None,
        "org_id": org_id,
        "device_id": device_id,
        "sn": sn,
        "type": cmd_type,
        "result": result,
        "code": code,
        "latency_ms": latency_ms,
        "owner_user_id": owner_user_id,
    }
    log.info("AUDIT: %s", json.dumps(data, ensure_ascii=False))


class RemoteInputService:
    def __init__(
        self,
        leases: LeaseRegistryProtocol = lease_registry,
        presence: PresenceRegistryProtocol = presence_registry,
        pending: PendingCommandRegistryProtocol = pending_registry,
        limiter: RateLimiter = rate_limiter,
    ) -> None:
        self.leases = leases
        self.presence = presence
        self.pending = pending
        self.limiter = limiter

    def _build_lease_response(self, lease: Lease) -> LeaseResponse:
        ws_path = f"/api/internal/v1/remote-input/ws/lease/{lease.lease_id}"
        return LeaseResponse(
            lease_id=lease.lease_id,
            sn=lease.sn,
            device_id=lease.device_id,
            org_id=lease.org_id,
            owner_user_id=lease.owner_user_id,
            owner_role=lease.owner_role,
            scope=lease.scope,
            owner_session_id=lease.owner_session_id,
            created_at=lease.created_at,
            expires_at=lease.expires_at,
            keepalive_sec=settings.remote_input.lease_keepalive_sec,
            ws_path=ws_path,
            stream_instance_id=lease.stream_instance_id,
            selected_desktop_id=lease.selected_desktop_id,
            selected_session_id=lease.selected_session_id,
            stream_mode=lease.stream_mode,
        )

    def _validate_role_and_scope(
        self,
        norm_role: str,
        scope: LeaseScope,
        is_superuser: bool = False,
    ) -> None:
        actual_superuser = norm_role in ("superuser", "root") or (
            is_superuser and norm_role == "superuser"
        )

        if scope == "console":
            if not actual_superuser:
                raise HTTPException(status_code=403, detail="scope_not_allowed")
            return

        if norm_role in ("viewer", "4"):
            if scope != "view":
                raise HTTPException(status_code=403, detail="scope_not_allowed")
            return

        if norm_role in ("admin", "user"):
            if scope not in ("view", "stream", "input"):
                raise HTTPException(status_code=403, detail="scope_not_allowed")
            return

        if actual_superuser:
            return

        raise HTTPException(status_code=403, detail="scope_not_allowed")

    async def acquire_lease(
        self,
        session: AsyncSession,
        sn: str,
        org_id: int,
        owner_user_id: str,
        owner_role: str,
        scope: LeaseScope = "input",
        owner_session_id: str = "",
        ttl_sec: int | None = None,
        is_superuser: bool = False,
    ) -> LeaseResponse:
        norm_role = str(owner_role).strip().lower()
        self._validate_role_and_scope(norm_role, scope, is_superuser=is_superuser)

        device_id = await DeviceRepo.get_device_id(session, sn=sn, org_id=org_id)
        if device_id is None:
            raise HTTPException(
                status_code=403,
                detail="device not available for organization",
            )

        if scope == "view":
            agent_view = await self.presence.get(sn)
            stream_state = agent_view.stream.state if agent_view.stream else "stopped"
            if stream_state != "running":
                raise HTTPException(status_code=409, detail="stream_not_running")

        lease_ttl = (
            ttl_sec if ttl_sec is not None else settings.remote_input.lease_ttl_sec
        )

        try:
            lease = await self.leases.acquire(
                org_id=org_id,
                device_id=device_id,
                sn=sn,
                owner_user_id=owner_user_id,
                owner_role=norm_role,
                ttl_sec=lease_ttl,
                scope=scope,
                owner_session_id=owner_session_id,
            )
        except LeaseConflictError as err:
            log_audit(
                "lease_conflict",
                lease_id=err.active_lease.lease_id,
                org_id=org_id,
                device_id=device_id,
                sn=sn,
                owner_user_id=err.active_lease.owner_user_id,
                code="lease_taken",
            )
            raise HTTPException(
                status_code=409,
                detail=err.to_dict(),
            )

        log_audit(
            "lease_acquired",
            lease_id=lease.lease_id,
            org_id=org_id,
            device_id=device_id,
            sn=sn,
            owner_user_id=owner_user_id,
        )
        return self._build_lease_response(lease)

    async def upgrade_scope(
        self,
        lease_id: UUID,
        org_id: int,
        new_scope: LeaseScope,
        caller_user_id: str,
        caller_session_id: str,
        caller_role: str,
        is_superuser: bool = False,
    ) -> LeaseResponse:
        lease = await self.leases.get(lease_id)
        if lease is None or not lease.is_active():
            raise HTTPException(status_code=404, detail="lease not found or expired")

        if not is_superuser and lease.org_id != org_id:
            raise HTTPException(
                status_code=403, detail="cross-tenant lease access forbidden"
            )

        if not is_superuser:
            if lease.owner_user_id != caller_user_id:
                raise HTTPException(status_code=403, detail="lease ownership mismatch")
            if caller_session_id and lease.owner_session_id != caller_session_id:
                raise HTTPException(status_code=403, detail="lease session mismatch")

        norm_role = str(caller_role).strip().lower()
        self._validate_role_and_scope(norm_role, new_scope, is_superuser=is_superuser)

        if new_scope == "view":
            agent_view = await self.presence.get(lease.sn)
            stream_state = agent_view.stream.state if agent_view.stream else "stopped"
            if stream_state != "running":
                raise HTTPException(status_code=409, detail="stream_not_running")

        upgraded = await self.leases.upgrade_scope(lease_id, new_scope)
        if upgraded is None:
            raise HTTPException(status_code=404, detail="lease not found or expired")

        log_audit(
            "lease_scope_upgraded",
            lease_id=upgraded.lease_id,
            org_id=upgraded.org_id,
            device_id=upgraded.device_id,
            sn=upgraded.sn,
            owner_user_id=upgraded.owner_user_id,
            code=new_scope,
        )
        return self._build_lease_response(upgraded)

    async def keepalive(
        self,
        lease_id: UUID,
        org_id: int,
        caller_user_id: str | None = None,
        caller_session_id: str | None = None,
        is_superuser: bool = False,
    ) -> LeaseResponse:
        lease = await self.leases.get(lease_id)
        if lease is None or not lease.is_active():
            raise HTTPException(status_code=404, detail="lease not found or expired")

        if not is_superuser and lease.org_id != org_id:
            raise HTTPException(
                status_code=403, detail="cross-tenant lease access forbidden"
            )

        if not is_superuser:
            if caller_user_id and lease.owner_user_id != caller_user_id:
                raise HTTPException(status_code=403, detail="lease ownership mismatch")
            if caller_session_id and lease.owner_session_id != caller_session_id:
                raise HTTPException(status_code=403, detail="lease session mismatch")

        touched = await self.leases.touch(lease_id, settings.remote_input.lease_ttl_sec)
        if touched is None:
            raise HTTPException(status_code=404, detail="lease not found or expired")

        log_audit(
            "lease_keepalive",
            lease_id=touched.lease_id,
            org_id=touched.org_id,
            device_id=touched.device_id,
            sn=touched.sn,
            owner_user_id=touched.owner_user_id,
        )
        return self._build_lease_response(touched)

    async def release(
        self,
        lease_id: UUID,
        org_id: int,
        caller_user_id: str | None = None,
        caller_session_id: str | None = None,
        is_superuser: bool = False,
    ) -> None:
        lease = await self.leases.get(lease_id)
        if lease is None:
            raise HTTPException(status_code=404, detail="lease not found")

        if not is_superuser and lease.org_id != org_id:
            raise HTTPException(
                status_code=403, detail="cross-tenant lease access forbidden"
            )

        if not is_superuser:
            if caller_user_id and lease.owner_user_id != caller_user_id:
                raise HTTPException(status_code=403, detail="lease ownership mismatch")
            if caller_session_id and lease.owner_session_id != caller_session_id:
                raise HTTPException(status_code=403, detail="lease session mismatch")

        await self.leases.revoke(lease_id, reason="released")
        await self.pending.cancel_for_lease(lease_id, reason="released")
        await self.limiter.cleanup_lease(lease_id)

        log_audit(
            "lease_released",
            lease_id=lease.lease_id,
            org_id=lease.org_id,
            device_id=lease.device_id,
            sn=lease.sn,
            owner_user_id=lease.owner_user_id,
        )

    async def release_by_owner(
        self,
        user_id: str,
        session_id: str | None = None,
    ) -> dict[str, int]:
        revoked = await self.leases.revoke_by_owner(
            user_id, session_id, reason="owner_logout"
        )
        for lse in revoked:
            await self.pending.cancel_for_lease(lse.lease_id, reason="owner_logout")
            await self.limiter.cleanup_lease(lse.lease_id)
            log_audit(
                "lease_released_by_owner",
                lease_id=lse.lease_id,
                org_id=lse.org_id,
                device_id=lse.device_id,
                sn=lse.sn,
                owner_user_id=user_id,
            )
        return {"revoked_count": len(revoked)}

    async def get_status(
        self,
        session: AsyncSession,
        sn: str,
        org_id: int,
    ) -> StatusResponse:
        device_id = await DeviceRepo.get_device_id(session, sn=sn, org_id=org_id)
        if device_id is None:
            raise HTTPException(
                status_code=403,
                detail="device not available for organization",
            )

        agent_view = await self.presence.get(sn)
        active_lease = await self.leases.get_active(sn)

        if active_lease is not None and active_lease.is_active():
            lease_view = LeaseStatusView(
                active=True,
                lease_id=active_lease.lease_id,
                scope=active_lease.scope,
                owner_role=active_lease.owner_role,
                owner_user_id=active_lease.owner_user_id,
                owner_masked=mask_user_id(active_lease.owner_user_id),
                expires_at=active_lease.expires_at.isoformat(),
                stream_instance_id=active_lease.stream_instance_id,
                selected_desktop_id=active_lease.selected_desktop_id,
            )
        else:
            lease_view = LeaseStatusView(active=False)

        return StatusResponse(sn=sn, agent=agent_view, lease=lease_view)

    async def get_inventory(
        self,
        session: AsyncSession,
        sn: str,
        org_id: int,
        refresh: bool = False,
        caller_user_id: str | None = None,
        caller_session_id: str | None = None,
        is_superuser: bool = False,
    ) -> InventoryInfo:
        device_id = await DeviceRepo.get_device_id(session, sn=sn, org_id=org_id)
        if device_id is None:
            raise HTTPException(
                status_code=403,
                detail="device not available for organization",
            )

        if refresh:
            active_lease = await self.leases.get_active(sn)
            if active_lease is None or not active_lease.is_active():
                raise HTTPException(
                    status_code=409, detail="lease_required_for_refresh"
                )
            if not is_superuser:
                if caller_user_id and active_lease.owner_user_id != caller_user_id:
                    raise HTTPException(
                        status_code=403, detail="lease ownership mismatch"
                    )
                if (
                    caller_session_id
                    and active_lease.owner_session_id != caller_session_id
                ):
                    raise HTTPException(
                        status_code=403, detail="lease session mismatch"
                    )

            cmd_id = uuid4()
            now_ms = int(time.time() * 1000)
            timeout_sec = settings.remote_input.inventory_timeout_sec
            ttl_ms = int(timeout_sec * 1000)

            cmd = InventoryGetCommand(
                command_id=cmd_id,
                lease_id=active_lease.lease_id,
                sn=sn,
                issued_at_ms=now_ms,
                expires_at_ms=now_ms + ttl_ms,
            )
            future = await self.pending.register(
                command_id=cmd_id,
                lease_id=active_lease.lease_id,
                sn=sn,
                cmd_type="inventory_get",
                timeout_sec=float(timeout_sec),
            )
            await send_ctl_command(sn, cmd, ttl_ms=ttl_ms)

            try:
                res = await asyncio.wait_for(future, timeout=float(timeout_sec))
            except TimeoutError, asyncio.TimeoutError:
                raise HTTPException(status_code=504, detail="terminal_timeout")

            if res.result == "nack":
                raise HTTPException(
                    status_code=409, detail=res.code or "inventory_failed"
                )
            if res.inventory is not None:
                await self.presence.update_inventory(sn, res.inventory)

        return await self.presence.get_inventory(sn)

    async def stream_start(
        self,
        lease_id: UUID,
        org_id: int,
        mode: Literal["desktop", "usb-camera"],
        source_id: str,
        profile: str = "default",
        caller_user_id: str | None = None,
        caller_session_id: str | None = None,
        is_superuser: bool = False,
    ) -> StreamStartResponse:
        lease = await self.leases.get(lease_id)
        if lease is None or not lease.is_active():
            raise HTTPException(status_code=409, detail="lease inactive")

        if not is_superuser and lease.org_id != org_id:
            raise HTTPException(
                status_code=403, detail="cross-tenant lease access forbidden"
            )

        if not is_superuser:
            if caller_user_id and lease.owner_user_id != caller_user_id:
                raise HTTPException(status_code=403, detail="lease ownership mismatch")
            if caller_session_id and lease.owner_session_id != caller_session_id:
                raise HTTPException(status_code=403, detail="lease session mismatch")

        if lease.scope not in ("stream", "input"):
            raise HTTPException(status_code=403, detail="scope_not_allowed")

        stream_instance_id = uuid4()
        cmd_id = uuid4()
        now_ms = int(time.time() * 1000)
        timeout_sec = settings.remote_input.stream_start_timeout_sec
        ttl_ms = int(timeout_sec * 1000)

        cmd = StreamStartCommand(
            command_id=cmd_id,
            lease_id=lease.lease_id,
            sn=lease.sn,
            mode=mode,
            source_id=source_id,
            profile=profile,
            stream_instance_id=stream_instance_id,
            issued_at_ms=now_ms,
            expires_at_ms=now_ms + ttl_ms,
        )

        future = await self.pending.register(
            command_id=cmd_id,
            lease_id=lease.lease_id,
            sn=lease.sn,
            cmd_type="stream_start",
            timeout_sec=float(timeout_sec),
        )

        await send_ctl_command(lease.sn, cmd, ttl_ms=ttl_ms)

        try:
            res = await asyncio.wait_for(future, timeout=float(timeout_sec))
        except TimeoutError, asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="terminal_timeout")

        if res.result == "nack":
            raise HTTPException(
                status_code=409, detail=res.code or "stream_start_failed"
            )

        if res.result in ("started", "already_running", "switched"):
            lease.stream_instance_id = stream_instance_id
            lease.stream_mode = mode
            if mode == "desktop":
                inv = await self.presence.get_inventory(lease.sn)
                matched_disp = next(
                    (d for d in inv.displays if d.desktop_id == source_id), None
                )
                lease.selected_desktop_id = source_id
                lease.selected_session_id = (
                    matched_disp.session_id if matched_disp else None
                )
            else:
                lease.selected_desktop_id = None
                lease.selected_session_id = None

        return StreamStartResponse(
            stream_instance_id=stream_instance_id,
            result=res.result,
            state=res.state or "running",
        )

    async def stream_stop(
        self,
        lease_id: UUID,
        org_id: int,
        caller_user_id: str | None = None,
        caller_session_id: str | None = None,
        is_superuser: bool = False,
    ) -> StreamStopResponse:
        lease = await self.leases.get(lease_id)
        if lease is None or not lease.is_active():
            raise HTTPException(status_code=409, detail="lease inactive")

        if not is_superuser and lease.org_id != org_id:
            raise HTTPException(
                status_code=403, detail="cross-tenant lease access forbidden"
            )

        if not is_superuser:
            if caller_user_id and lease.owner_user_id != caller_user_id:
                raise HTTPException(status_code=403, detail="lease ownership mismatch")
            if caller_session_id and lease.owner_session_id != caller_session_id:
                raise HTTPException(status_code=403, detail="lease session mismatch")

        if lease.scope not in ("stream", "input"):
            raise HTTPException(status_code=403, detail="scope_not_allowed")

        cmd_id = uuid4()
        now_ms = int(time.time() * 1000)
        timeout_sec = 10.0
        ttl_ms = int(timeout_sec * 1000)

        cmd = StreamStopCommand(
            command_id=cmd_id,
            lease_id=lease.lease_id,
            sn=lease.sn,
            stream_instance_id=lease.stream_instance_id,
            issued_at_ms=now_ms,
            expires_at_ms=now_ms + ttl_ms,
        )

        future = await self.pending.register(
            command_id=cmd_id,
            lease_id=lease.lease_id,
            sn=lease.sn,
            cmd_type="stream_stop",
            timeout_sec=float(timeout_sec),
        )

        await send_ctl_command(lease.sn, cmd, ttl_ms=ttl_ms)

        try:
            res = await asyncio.wait_for(future, timeout=float(timeout_sec))
        except TimeoutError, asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="terminal_timeout")

        if res.result == "nack":
            raise HTTPException(
                status_code=409, detail=res.code or "stream_stop_failed"
            )

        # Stream stopped
        lease.stream_instance_id = None
        lease.stream_mode = None
        lease.selected_desktop_id = None
        lease.selected_session_id = None

        return StreamStopResponse(result=res.result or "stopped")

    def _validate_input_command(
        self,
        lease: Lease,
        org_id: int,
        caller_user_id: str | None,
        caller_session_id: str | None,
        desktop_id: str | None,
        stream_instance_id: UUID | None,
        is_superuser: bool = False,
    ) -> None:
        if not lease.is_active():
            raise HTTPException(status_code=409, detail="lease inactive")

        if not is_superuser and lease.org_id != org_id:
            raise HTTPException(
                status_code=403, detail="cross-tenant lease access forbidden"
            )

        if not is_superuser:
            if caller_user_id and lease.owner_user_id != caller_user_id:
                raise HTTPException(status_code=403, detail="lease ownership mismatch")
            if caller_session_id and lease.owner_session_id != caller_session_id:
                raise HTTPException(status_code=403, detail="lease session mismatch")

        if lease.scope != "input":
            raise HTTPException(status_code=403, detail="scope_not_allowed")

        if lease.stream_mode != "desktop":
            raise HTTPException(
                status_code=409, detail="input_not_allowed_in_camera_mode"
            )

        if desktop_id is not None and desktop_id != lease.selected_desktop_id:
            raise HTTPException(status_code=409, detail="desktop_mismatch")

        if (
            stream_instance_id is not None
            and stream_instance_id != lease.stream_instance_id
        ):
            raise HTTPException(status_code=409, detail="stream_mismatch")

    async def pointer_move(
        self,
        lease_id: UUID,
        org_id: int,
        x: int,
        y: int,
        desktop_id: str | None = None,
        stream_instance_id: UUID | None = None,
        caller_user_id: str | None = None,
        caller_session_id: str | None = None,
        is_superuser: bool = False,
        skip_rate_limit: bool = False,
    ) -> dict[str, bool]:
        lease = await self.leases.get(lease_id)
        if lease is None:
            raise HTTPException(status_code=409, detail="lease inactive")

        self._validate_input_command(
            lease,
            org_id,
            caller_user_id,
            caller_session_id,
            desktop_id,
            stream_instance_id,
            is_superuser=is_superuser,
        )

        if not skip_rate_limit:
            allowed = await self.limiter.check_rate_limit(
                lease_id,
                "pointer_move",
                settings.remote_input.move_rate_per_sec,
            )
            if not allowed:
                raise HTTPException(status_code=429, detail="rate limited")

        now_ms = int(time.time() * 1000)
        command_id = uuid4()
        cmd = PointerMoveCommand(
            command_id=command_id,
            lease_id=lease.lease_id,
            sn=lease.sn,
            x=x,
            y=y,
            desktop_id=lease.selected_desktop_id,
            stream_instance_id=lease.stream_instance_id,
            issued_at_ms=now_ms,
            expires_at_ms=now_ms + settings.remote_input.move_ttl_ms,
        )

        await send_ctl_command(lease.sn, cmd, settings.remote_input.move_ttl_ms)
        return {"accepted": True}

    async def mouse_click(
        self,
        lease_id: UUID,
        org_id: int,
        x: int,
        y: int,
        button: Literal["left"] = "left",
        client_ref: str | None = None,
        desktop_id: str | None = None,
        stream_instance_id: UUID | None = None,
        caller_user_id: str | None = None,
        caller_session_id: str | None = None,
        is_superuser: bool = False,
        skip_rate_limit: bool = False,
    ) -> ClickResult:
        lease = await self.leases.get(lease_id)
        if lease is None:
            raise HTTPException(status_code=409, detail="lease inactive")

        self._validate_input_command(
            lease,
            org_id,
            caller_user_id,
            caller_session_id,
            desktop_id,
            stream_instance_id,
            is_superuser=is_superuser,
        )

        if not skip_rate_limit:
            allowed = await self.limiter.check_rate_limit(
                lease_id,
                "mouse_click",
                settings.remote_input.click_rate_per_sec,
            )
            if not allowed:
                raise HTTPException(status_code=429, detail="rate limited")

        command_id = uuid4()
        now_ms = int(time.time() * 1000)
        t_start = time.monotonic()

        cmd = MouseClickCommand(
            command_id=command_id,
            lease_id=lease.lease_id,
            sn=lease.sn,
            x=x,
            y=y,
            button=button,
            desktop_id=lease.selected_desktop_id,
            stream_instance_id=lease.stream_instance_id,
            issued_at_ms=now_ms,
            expires_at_ms=now_ms + settings.remote_input.click_ttl_ms,
        )

        future = await self.pending.register(
            command_id=command_id,
            lease_id=lease.lease_id,
            sn=lease.sn,
            cmd_type="mouse_click",
            timeout_sec=settings.remote_input.click_ack_timeout_ms / 1000.0,
        )

        await send_ctl_command(lease.sn, cmd, settings.remote_input.click_ttl_ms)

        timeout_sec = settings.remote_input.click_ack_timeout_ms / 1000.0
        try:
            pending_res = await asyncio.wait_for(future, timeout=timeout_sec)
        except TimeoutError, asyncio.TimeoutError:
            pending_res = None

        latency_ms = int((time.monotonic() - t_start) * 1000)

        if pending_res is None:
            log_audit(
                "command_dispatch",
                lease_id=lease.lease_id,
                org_id=lease.org_id,
                device_id=lease.device_id,
                sn=lease.sn,
                cmd_type="mouse_click",
                result="unconfirmed",
                code="ack_timeout",
                latency_ms=latency_ms,
                owner_user_id=lease.owner_user_id,
            )
            return ClickResult(
                command_id=command_id,
                client_ref=client_ref,
                result="unconfirmed",
                code="ack_timeout",
                message="Click dispatch timeout (no ACK/NACK received)",
                latency_ms=latency_ms,
            )

        log_audit(
            "command_dispatch",
            lease_id=lease.lease_id,
            org_id=lease.org_id,
            device_id=lease.device_id,
            sn=lease.sn,
            cmd_type="mouse_click",
            result=pending_res.result,
            code=pending_res.code,
            latency_ms=latency_ms,
            owner_user_id=lease.owner_user_id,
        )

        res_type: Literal["injected", "nack", "unconfirmed"] = (
            "injected"
            if pending_res.result == "injected"
            else "nack" if pending_res.result == "nack" else "unconfirmed"
        )

        return ClickResult(
            command_id=command_id,
            client_ref=client_ref,
            result=res_type,
            code=pending_res.code,
            message=pending_res.message,
            latency_ms=latency_ms,
        )

    async def key_event(
        self,
        lease_id: UUID,
        org_id: int,
        kind: Literal["down", "up", "press"],
        vk: int,
        text: str | None = None,
        client_ref: str | None = None,
        desktop_id: str | None = None,
        stream_instance_id: UUID | None = None,
        caller_user_id: str | None = None,
        caller_session_id: str | None = None,
        is_superuser: bool = False,
        skip_rate_limit: bool = False,
    ) -> KeyResult:
        if vk not in ALLOWED_VK_CODES:
            raise HTTPException(status_code=400, detail="vk_not_allowed")

        if text is not None and len(text) > 32:
            raise HTTPException(status_code=400, detail="text_too_long")

        lease = await self.leases.get(lease_id)
        if lease is None:
            raise HTTPException(status_code=409, detail="lease inactive")

        self._validate_input_command(
            lease,
            org_id,
            caller_user_id,
            caller_session_id,
            desktop_id,
            stream_instance_id,
            is_superuser=is_superuser,
        )

        if not skip_rate_limit:
            allowed = await self.limiter.check_rate_limit(
                lease_id,
                "key_event",
                settings.remote_input.move_rate_per_sec,
            )
            if not allowed:
                raise HTTPException(status_code=429, detail="rate limited")

        command_id = uuid4()
        now_ms = int(time.time() * 1000)
        t_start = time.monotonic()

        cmd = KeyEventCommand(
            command_id=command_id,
            lease_id=lease.lease_id,
            sn=lease.sn,
            desktop_id=lease.selected_desktop_id,
            stream_instance_id=lease.stream_instance_id,
            kind=kind,
            vk=vk,
            text=text,
            issued_at_ms=now_ms,
            expires_at_ms=now_ms + settings.remote_input.click_ttl_ms,
        )

        future = await self.pending.register(
            command_id=command_id,
            lease_id=lease.lease_id,
            sn=lease.sn,
            cmd_type="key_event",
            timeout_sec=settings.remote_input.click_ack_timeout_ms / 1000.0,
        )

        await send_ctl_command(lease.sn, cmd, settings.remote_input.click_ttl_ms)

        timeout_sec = settings.remote_input.click_ack_timeout_ms / 1000.0
        try:
            pending_res = await asyncio.wait_for(future, timeout=timeout_sec)
        except TimeoutError, asyncio.TimeoutError:
            pending_res = None

        latency_ms = int((time.monotonic() - t_start) * 1000)

        if pending_res is None:
            log_audit(
                "command_dispatch",
                lease_id=lease.lease_id,
                org_id=lease.org_id,
                device_id=lease.device_id,
                sn=lease.sn,
                cmd_type="key_event",
                result="unconfirmed",
                code="ack_timeout",
                latency_ms=latency_ms,
                owner_user_id=lease.owner_user_id,
            )
            return KeyResult(
                command_id=command_id,
                client_ref=client_ref,
                result="unconfirmed",
                code="ack_timeout",
                message="Key event dispatch timeout (no ACK/NACK received)",
                latency_ms=latency_ms,
            )

        log_audit(
            "command_dispatch",
            lease_id=lease.lease_id,
            org_id=lease.org_id,
            device_id=lease.device_id,
            sn=lease.sn,
            cmd_type="key_event",
            result=pending_res.result,
            code=pending_res.code,
            latency_ms=latency_ms,
            owner_user_id=lease.owner_user_id,
        )

        res_type: Literal["injected", "nack", "unconfirmed"] = (
            "injected"
            if pending_res.result == "injected"
            else "nack" if pending_res.result == "nack" else "unconfirmed"
        )

        return KeyResult(
            command_id=command_id,
            client_ref=client_ref,
            result=res_type,
            code=pending_res.code,
            message=pending_res.message,
            latency_ms=latency_ms,
        )


remote_input_service = RemoteInputService()
