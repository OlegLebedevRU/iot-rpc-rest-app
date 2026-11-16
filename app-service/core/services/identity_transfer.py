"""Explicit PB-owned identity transfer, retaining device security restrictions."""

import hashlib
import json
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.crud.device_repo import DeviceRepo
from core.models.device_provisioning import DeviceProvisioning
from core.models.device_tasks import DevTask, DevTaskStatus
from core.models.common import TaskStatus
from core.models.devices import Device, DeviceOrgBind, DeviceTag, Org
from core.models.remote_sessions import RemoteSession
from core.remote_input.leases import lease_registry
from core.schemas.remote_sessions import RemoteSessionStop
from core.services.remote_session_event_service import remote_session_event_service


class IdentityTransferRequest(BaseModel):
    operation_id: UUID
    terminal_id: int = Field(gt=0)
    device_id: int = Field(gt=0)
    sn: str = Field(min_length=1, max_length=64)
    source_org_id: int = Field(gt=0)
    target_org_id: int = Field(gt=0)


async def transfer_identity(
    session: AsyncSession, request: IdentityTransferRequest
) -> dict:
    if request.source_org_id == request.target_org_id:
        raise HTTPException(409, "identity_same_tenant")
    # The same binding lock is held by lease and durable session acquisition.
    row = (
        await session.execute(
            select(Device, DeviceOrgBind)
            .join(DeviceOrgBind, DeviceOrgBind.device_id == Device.device_id)
            .where(
                Device.device_id == request.device_id,
                Device.sn == request.sn,
                Device.is_deleted.is_(False),
            )
            .with_for_update(of=DeviceOrgBind)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(404, "identity_device_not_found")
    device, binding = row
    target = await session.scalar(
        select(Org).where(
            Org.org_id == request.target_org_id, Org.is_deleted.is_(False)
        )
    )
    if target is None:
        raise HTTPException(409, "identity_target_not_found")
    digest = hashlib.sha256(
        json.dumps(
            request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    marker = await session.scalar(
        select(DeviceTag).where(
            DeviceTag.device_id == device.device_id,
            DeviceTag.tag == "identity_transfer",
            DeviceTag.is_system_tag.is_(True),
            DeviceTag.is_deleted.is_(False),
        )
    )
    if binding.org_id == request.target_org_id:
        if marker is None or marker.value != digest:
            raise HTTPException(409, "identity_operation_mismatch")
        await session.rollback()
        return {
            "status": "completed",
            "operation_id": str(request.operation_id),
            "org_id": request.target_org_id,
            "sn": request.sn,
        }
    if binding.org_id != request.source_org_id:
        raise HTTPException(409, "identity_source_mismatch")
    provisionings = list(
        (
            await session.scalars(
                select(DeviceProvisioning)
                .where(DeviceProvisioning.sn == request.sn)
                .with_for_update()
            )
        ).all()
    )
    if any(
        item.tenant_id != request.source_org_id
        or item.terminal_id != request.terminal_id
        for item in provisionings
    ):
        raise HTTPException(409, "identity_provisioning_mismatch")
    # Revoke input/file/desktop leases and close old console/video sessions BEFORE
    # changing org. Failure is surfaced to PB for an actionable administrator incident.
    lease = await lease_registry.get_active_by_sn(request.sn)
    if lease is not None:
        revoked = await lease_registry.revoke(
            lease.lease_id, reason="identity_transfer"
        )
        if revoked is None:
            raise HTTPException(409, "identity_lease_revoke_failed")
    sessions = list(
        (
            await session.scalars(
                select(RemoteSession)
                .where(
                    RemoteSession.sn == request.sn,
                    RemoteSession.status.in_(
                        ["requested", "starting", "active", "stopping"]
                    ),
                )
                .with_for_update()
            )
        ).all()
    )
    for active in sessions:
        await remote_session_event_service.stop_session(
            session,
            active.session_id,
            RemoteSessionStop(
                tenant_id=active.tenant_id,
                sn=request.sn,
                reason="identity_transfer",
                operation_id=str(request.operation_id),
                timeout_sec=1,
            ),
        )
    await session.execute(
        update(DevTask)
        .where(DevTask.device_id == device.device_id, DevTask.org_id.is_(None))
        .values(org_id=request.source_org_id)
    )
    expired = await session.execute(
        update(DevTaskStatus)
        .where(
            DevTaskStatus.task_id.in_(
                select(DevTask.id).where(
                    DevTask.device_id == device.device_id,
                    DevTask.org_id == request.source_org_id,
                )
            ),
            DevTaskStatus.status.in_(
                [TaskStatus.READY, TaskStatus.PENDING, TaskStatus.LOCK]
            ),
        )
        .values(status=TaskStatus.EXPIRED, ttl=0, expires_at=func.clock_timestamp())
        .returning(DevTaskStatus.task_id)
    )
    expired_ids = list(expired.scalars().all())
    if expired_ids:
        from core.crud.dev_tasks_repo import TasksRepository

        await TasksRepository.scrub_renewal_payload(session, expired_ids)
    binding.org_id = request.target_org_id
    for item in provisionings:
        item.tenant_id = request.target_org_id
        # Old operation IDs remain a history record; owner endpoints now see the target.
    if marker is None:
        session.add(
            DeviceTag(
                device_id=device.device_id,
                tag="identity_transfer",
                value=digest,
                is_system_tag=True,
                is_deleted=False,
            )
        )
    else:
        marker.value = digest
    await DeviceRepo.add_audit_log(
        session,
        device_id=device.device_id,
        org_id=request.target_org_id,
        event_type="IDENTITY_TRANSFER",
        actor="processing-backend",
        details={
            "operation_id": str(request.operation_id),
            "source_org_id": request.source_org_id,
            "target_org_id": request.target_org_id,
            "sn": request.sn,
        },
    )
    await session.commit()
    # Device broker credentials and topic ACLs are SN-based and remain unchanged.
    # No provisioning upsert: is_blocked and collision restrictions are preserved.
    return {
        "status": "completed",
        "operation_id": str(request.operation_id),
        "org_id": request.target_org_id,
        "sn": request.sn,
    }
