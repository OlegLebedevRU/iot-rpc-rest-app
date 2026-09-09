from __future__ import annotations

import asyncio
import json
import time
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
)
from core.remote_input.pending import (
    PendingCommandRegistryProtocol,
    PendingResult,
    pending_registry,
)
from core.remote_input.presence import (
    PresenceRegistryProtocol,
    presence_registry,
)
from core.remote_input.publisher import send_ctl_command
from core.remote_input.rate_limit import RateLimiter, rate_limiter
from core.remote_input.schemas import (
    ClickResult,
    LeaseResponse,
    LeaseStatusView,
    MouseClickCommand,
    PointerMoveCommand,
    StatusResponse,
)

log = setup_module_logger(__name__, "remote_input.log")


def log_audit(
    event: str,
    *,
    command_id: UUID | str | None = None,
    lease_id: UUID | str | None = None,
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
        "command_id": str(command_id) if command_id else None,
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
            created_at=lease.created_at,
            expires_at=lease.expires_at,
            keepalive_sec=settings.remote_input.lease_keepalive_sec,
            ws_path=ws_path,
        )

    async def acquire_lease(
        self,
        session: AsyncSession,
        sn: str,
        org_id: int,
        owner_user_id: str,
        owner_role: str,
    ) -> LeaseResponse:
        norm_role = str(owner_role).strip().lower()
        if norm_role in ("viewer", "4"):
            raise HTTPException(
                status_code=403, detail="role not allowed for remote input"
            )

        device_id = await DeviceRepo.get_device_id(session, sn=sn, org_id=org_id)
        if device_id is None:
            raise HTTPException(
                status_code=403,
                detail="device not available for organization",
            )

        try:
            lease = await self.leases.acquire(
                org_id=org_id,
                device_id=device_id,
                sn=sn,
                owner_user_id=owner_user_id,
                owner_role=norm_role,
                ttl_sec=settings.remote_input.lease_ttl_sec,
            )
        except LeaseConflictError as err:
            active = err.active_lease
            log_audit(
                "lease_conflict",
                lease_id=active.lease_id,
                org_id=org_id,
                device_id=device_id,
                sn=sn,
                owner_user_id=active.owner_user_id,
                code="lease_busy",
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "detail": "lease busy",
                    "owner_user_id": active.owner_user_id,
                    "expires_at": active.expires_at.isoformat(),
                },
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

    async def keepalive(
        self,
        lease_id: UUID,
        org_id: int,
        is_superuser: bool = False,
    ) -> LeaseResponse:
        lease = await self.leases.get(lease_id)
        if lease is None or not lease.is_active():
            raise HTTPException(status_code=404, detail="lease not found or expired")

        if not is_superuser and lease.org_id != org_id:
            raise HTTPException(
                status_code=403, detail="cross-tenant lease access forbidden"
            )

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
        is_superuser: bool = False,
    ) -> None:
        lease = await self.leases.get(lease_id)
        if lease is None:
            raise HTTPException(status_code=404, detail="lease not found")

        if not is_superuser and lease.org_id != org_id:
            raise HTTPException(
                status_code=403, detail="cross-tenant lease access forbidden"
            )

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
                owner_user_id=active_lease.owner_user_id,
                expires_at=active_lease.expires_at.isoformat(),
            )
        else:
            lease_view = LeaseStatusView(active=False)

        return StatusResponse(sn=sn, agent=agent_view, lease=lease_view)

    async def pointer_move(
        self,
        lease_id: UUID,
        org_id: int,
        x: int,
        y: int,
        is_superuser: bool = False,
        skip_rate_limit: bool = False,
    ) -> dict[str, bool]:
        lease = await self.leases.get(lease_id)
        if lease is None or not lease.is_active():
            raise HTTPException(status_code=409, detail="lease inactive")

        if not is_superuser and lease.org_id != org_id:
            raise HTTPException(
                status_code=403, detail="cross-tenant lease access forbidden"
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
        button: str = "left",
        client_ref: str | None = None,
        is_superuser: bool = False,
        skip_rate_limit: bool = False,
    ) -> ClickResult:
        lease = await self.leases.get(lease_id)
        if lease is None or not lease.is_active():
            raise HTTPException(status_code=409, detail="lease inactive")

        if not is_superuser and lease.org_id != org_id:
            raise HTTPException(
                status_code=403, detail="cross-tenant lease access forbidden"
            )

        if not skip_rate_limit:
            allowed = await self.limiter.check_rate_limit(
                lease_id,
                "mouse_click",
                settings.remote_input.click_rate_per_sec,
            )
            if not allowed:
                raise HTTPException(status_code=429, detail="rate limited")

        now_ms = int(time.time() * 1000)
        command_id = uuid4()
        cmd = MouseClickCommand(
            command_id=command_id,
            lease_id=lease.lease_id,
            sn=lease.sn,
            x=x,
            y=y,
            button="left",
            issued_at_ms=now_ms,
            expires_at_ms=now_ms + settings.remote_input.click_ttl_ms,
        )

        fut = await self.pending.register(
            command_id=command_id,
            lease_id=lease.lease_id,
            sn=lease.sn,
            cmd_type="mouse_click",
        )

        start_time = time.monotonic()
        try:
            await send_ctl_command(lease.sn, cmd, settings.remote_input.click_ttl_ms)

            res: PendingResult = await asyncio.wait_for(
                fut,
                timeout=settings.remote_input.click_ack_timeout_ms / 1000.0,
            )
            latency_ms = int((time.monotonic() - start_time) * 1000)
            result = res.result
            code = res.code
            message = res.message
        except asyncio.TimeoutError:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            result = "unconfirmed"
            code = "ack_timeout"
            message = "Click ACK timeout expired"
            await self.pending.resolve(
                command_id,
                PendingResult(
                    result="unconfirmed",
                    code=code,
                    message=message,
                ),
            )
        except Exception as exc:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            result = "unconfirmed"
            code = "error"
            message = str(exc)
            await self.pending.resolve(
                command_id,
                PendingResult(
                    result="unconfirmed",
                    code=code,
                    message=message,
                ),
            )

        log_audit(
            "mouse_click",
            command_id=command_id,
            lease_id=lease.lease_id,
            org_id=lease.org_id,
            device_id=lease.device_id,
            sn=lease.sn,
            cmd_type="mouse_click",
            result=result,
            code=code,
            latency_ms=latency_ms,
            owner_user_id=lease.owner_user_id,
        )

        return ClickResult(
            command_id=command_id,
            client_ref=client_ref,
            result=result,
            code=code,
            message=message,
            latency_ms=latency_ms,
        )


remote_input_service = RemoteInputService()
