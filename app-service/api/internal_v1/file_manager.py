"""File-manager control only. No file bytes or storage URLs pass through IoT."""

from datetime import UTC, datetime
import secrets
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.internal_v1.internal_depends import Session_dep
from core.config import settings
from core.crud.device_repo import DeviceRepo
from core.remote_input.leases import LeaseConflictError, lease_registry
from core.schemas.device_tasks import TaskCreate
from core.services.device_tasks import DeviceTasksService


async def service_auth(x_internal_service_key: str = Header(default="")) -> None:
    key = settings.auth.internal_service_key
    if not key or not secrets.compare_digest(key, x_internal_service_key):
        raise HTTPException(401, "Service authentication required")


router = APIRouter(prefix="/file-manager", dependencies=[Depends(service_auth)])


class Signal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["start", "renew", "stop", "list", "transfer", "cancel"]
    operation_id: UUID | None = None

    @model_validator(mode="after")
    def validate_operation(self):
        needs_operation = self.action in ("list", "transfer", "cancel")
        if needs_operation != (self.operation_id is not None):
            raise ValueError("operation_id required only for list/transfer/cancel")
        return self


class Acquire(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ttl_sec: int = Field(default=60, ge=30, le=90)


def actor(request: Request) -> tuple[int, str, str, str]:
    try:
        tenant = int(request.headers.get("X-Org-Id", "0"))
    except ValueError as exc:
        raise HTTPException(403, "Tenant required") from exc
    user = request.headers.get("X-User-Id", "")
    session = request.headers.get("X-Session-Id", "")
    role = request.headers.get("X-Role", "")
    if (
        tenant <= 0
        or not user
        or not session
        or role not in ("superuser", "admin", "user", "l4desk_owner")
    ):
        raise HTTPException(403, "File-manager actor required")
    return tenant, user, session, role


async def owned_lease(lease_id: UUID, request: Request):
    tenant, user, session, _ = actor(request)
    lease = await lease_registry.get(lease_id)
    if (
        lease is None
        or lease.org_id != tenant
        or lease.owner_user_id != user
        or lease.owner_session_id != session
    ):
        raise HTTPException(404, "Session not found")
    if lease.scope != "files" or not lease.is_active():
        raise HTTPException(409, detail={"code": "lease_expired"})
    return lease


async def dispatch(db, lease, signal: Signal):
    method = {"list": 7020, "transfer": 7021, "cancel": 7022}.get(signal.action, 7023)
    payload = {
        "session_id": str(lease.lease_id),
        "action": signal.action,
        "expires_at": int(lease.expires_at.timestamp()),
        "ttl_sec": lease.ttl_sec,
    }
    if signal.operation_id is not None:
        payload["operation_id"] = str(signal.operation_id)
    task = await DeviceTasksService(db, lease.org_id).create(
        TaskCreate(
            device_id=lease.device_id,
            method_code=method,
            ext_task_id=f"fm:{lease.lease_id.hex[:8]}:{method}",
            priority=1,
            ttl=1,
            payload={"dt": [payload]},
        )
    )
    return {
        "lease_id": str(lease.lease_id),
        "scope": "files",
        "expires_at": lease.expires_at.isoformat(),
        "command_id": str(task.id),
        "keepalive_sec": 15,
    }


@router.post("/devices/{device_id}/sessions")
async def acquire(device_id: int, body: Acquire, request: Request, db: Session_dep):
    tenant, user, session, role = actor(request)
    sn = await DeviceRepo.get_device_sn(db, device_id=device_id, org_id=tenant)
    if sn is None:
        raise HTTPException(404, "Device not found")
    try:
        lease = await lease_registry.acquire(
            tenant,
            device_id,
            sn,
            user,
            role,
            body.ttl_sec,
            scope="files",
            owner_session_id=session,
        )
    except LeaseConflictError as exc:
        raise HTTPException(409, detail=exc.to_dict()) from exc
    return {
        "lease_id": str(lease.lease_id),
        "scope": "files",
        "expires_at": lease.expires_at.isoformat(),
        "keepalive_sec": 15,
    }


@router.get("/sessions/{lease_id}")
async def validate(lease_id: UUID, request: Request):
    lease = await owned_lease(lease_id, request)
    return {
        "lease_id": str(lease.lease_id),
        "device_id": lease.device_id,
        "sn": lease.sn,
        "org_id": lease.org_id,
        "expires_at": lease.expires_at.isoformat(),
        "server_time": datetime.now(UTC).isoformat(),
        "scope": "files",
    }


@router.post("/sessions/{lease_id}/signals")
async def signal(lease_id: UUID, body: Signal, request: Request, db: Session_dep):
    lease = await owned_lease(lease_id, request)
    if body.action == "renew":
        lease = await lease_registry.touch(lease_id, lease.ttl_sec)
        if lease is None:
            raise HTTPException(409, detail={"code": "lease_expired"})
    try:
        return await dispatch(db, lease, body)
    except Exception:
        await lease_registry.revoke(lease_id, reason="fm_delivery_failed")
        raise
    finally:
        if body.action in ("stop", "cancel"):
            await lease_registry.revoke(lease_id, reason="fm_user_closed")
