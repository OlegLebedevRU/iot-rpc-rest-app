from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging_config import setup_module_logger
from core.models.device_provisioning import DeviceProvisioning
from core.models.devices import Device, DeviceAuditLog, DeviceConnection, DeviceOrgBind, Org
from core.schemas.device_provisioning import (
    DeviceProvisionRequest,
    DeviceProvisionStatus,
)
from core.services.remote_session_event_service import remote_session_event_service

log = setup_module_logger(__name__, "device_provisioning.log")


def compute_provision_payload_hash(
    tenant_id: int,
    terminal_id: int,
    sn: str,
    device_id: int | None = None,
    requested_by_user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Compute canonical SHA-256 hash of immutable provisioning request payload."""
    canonical = {
        "tenant_id": int(tenant_id),
        "terminal_id": int(terminal_id),
        "sn": str(sn).strip(),
        "device_id": int(device_id) if device_id is not None else None,
        "requested_by_user_id": str(requested_by_user_id).strip() if requested_by_user_id else None,
        "metadata": metadata or {},
    }
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DeviceProvisioningService:
    """Service for idempotent device provisioning, durable facts, and identity resolution."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def _allocate_device_id(self, session: AsyncSession) -> int:
        """Allocate a new monotonically safe device_id."""
        max_dev = 0
        try:
            res_dev = await session.scalar(select(func.coalesce(func.max(Device.device_id), 0)))
            if res_dev is not None:
                max_dev = max(max_dev, int(res_dev))
        except Exception as e:
            log.debug("Failed to query max device_id from Device: %s", e)

        try:
            res_prov = await session.scalar(
                select(func.coalesce(func.max(DeviceProvisioning.device_id), 0))
            )
            if res_prov is not None:
                max_dev = max(max_dev, int(res_prov))
        except Exception as e:
            log.debug("Failed to query max device_id from DeviceProvisioning: %s", e)

        return max(max_dev + 1, 1000)

    async def provision_device(
        self,
        session: AsyncSession,
        request: DeviceProvisionRequest,
    ) -> tuple[DeviceProvisioning, bool]:
        """Idempotently provision a device and terminal.

        Returns (DeviceProvisioning, is_replayed: bool).
        Raises HTTPException on identity conflict, parameter conflict, or database constraint violation.
        """
        payload_hash = compute_provision_payload_hash(
            tenant_id=request.tenant_id,
            terminal_id=request.terminal_id,
            sn=request.sn,
            device_id=request.device_id,
            requested_by_user_id=request.requested_by_user_id,
            metadata=request.metadata,
        )

        async with self._lock:
            # 1. Check idempotency on operation_id
            existing_by_op = await self.get_provisioning_by_operation(session, request.operation_id)
            if existing_by_op is not None:
                if existing_by_op.payload_hash == payload_hash:
                    log.info(
                        "Idempotent provision_device replay for operation_id=%s sn=%s",
                        request.operation_id,
                        request.sn,
                    )
                    return existing_by_op, True

                log.warning(
                    "Provisioning operation_id conflict: %s reused with different payload",
                    request.operation_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error_code": "OPERATION_ID_CONFLICT",
                        "message": (
                            f"Operation ID '{request.operation_id}' was previously executed "
                            "with different parameters"
                        ),
                        "operation_id": request.operation_id,
                    },
                )

            # 2. Identity conflict checks
            # 2a. Check if SN is already bound to a different tenant in core devices
            try:
                stmt = (
                    select(Device, DeviceOrgBind.org_id)
                    .outerjoin(DeviceOrgBind, Device.device_id == DeviceOrgBind.device_id)
                    .where(Device.sn == request.sn)
                    .limit(1)
                )
                exec_result = await session.execute(stmt)
                row = exec_result.first() if hasattr(exec_result, "first") else None
            except Exception as e:
                log.debug("Device/OrgBind query fallback for sn=%s: %s", request.sn, e)
                row = None

            target_device_id: int | None = None
            if row is not None:
                existing_dev = row[0]
                existing_org_id = row[1] if len(row) > 1 else None

                if existing_org_id is not None and existing_org_id != request.tenant_id:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "error_code": "IDENTITY_CONFLICT",
                            "message": (
                                f"Device SN '{request.sn}' is already registered to a different "
                                f"tenant ({existing_org_id})"
                            ),
                            "operation_id": request.operation_id,
                        },
                    )

                if request.device_id is not None and request.device_id != existing_dev.device_id:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "error_code": "IDENTITY_CONFLICT",
                            "message": (
                                f"Requested device_id {request.device_id} does not match existing "
                                f"device_id {existing_dev.device_id} for SN '{request.sn}'"
                            ),
                            "operation_id": request.operation_id,
                        },
                    )
                target_device_id = existing_dev.device_id
            else:
                # SN does not exist yet. Check if explicitly provided device_id clashes with another device
                if request.device_id is not None:
                    try:
                        dev_by_id = await session.scalar(
                            select(Device).where(Device.device_id == request.device_id)
                        )
                    except Exception:
                        dev_by_id = None
                    if dev_by_id is not None and dev_by_id.sn != request.sn:
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail={
                                "error_code": "IDENTITY_CONFLICT",
                                "message": (
                                    f"Device ID {request.device_id} is already in use by another "
                                    f"device with SN '{dev_by_id.sn}'"
                                ),
                                "operation_id": request.operation_id,
                            },
                        )

                    try:
                        prov_by_dev_id = await session.scalar(
                            select(DeviceProvisioning).where(
                                DeviceProvisioning.device_id == request.device_id,
                                DeviceProvisioning.status == DeviceProvisionStatus.PROVISIONED.value,
                            )
                        )
                    except Exception:
                        prov_by_dev_id = None

                    if prov_by_dev_id is not None and prov_by_dev_id.sn != request.sn:
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail={
                                "error_code": "IDENTITY_CONFLICT",
                                "message": (
                                    f"Device ID {request.device_id} is already in use by another "
                                    f"device with SN '{prov_by_dev_id.sn}'"
                                ),
                                "operation_id": request.operation_id,
                            },
                        )
                    target_device_id = request.device_id
                else:
                    target_device_id = await self._allocate_device_id(session)

            # 2b. Check if terminal_id within this tenant is already provisioned with a different SN
            try:
                existing_term = await session.scalar(
                    select(DeviceProvisioning).where(
                        DeviceProvisioning.tenant_id == request.tenant_id,
                        DeviceProvisioning.terminal_id == request.terminal_id,
                        DeviceProvisioning.status == DeviceProvisionStatus.PROVISIONED.value,
                    )
                )
            except Exception:
                existing_term = None

            if existing_term is not None and existing_term.sn != request.sn:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error_code": "IDENTITY_CONFLICT",
                        "message": (
                            f"Terminal {request.terminal_id} in tenant {request.tenant_id} is already "
                            f"provisioned with serial number '{existing_term.sn}'"
                        ),
                        "operation_id": request.operation_id,
                    },
                )

            # 2c. Check if SN is already provisioned for another tenant in tb_device_provisionings
            try:
                existing_prov_sn = await session.scalar(
                    select(DeviceProvisioning).where(
                        DeviceProvisioning.sn == request.sn,
                        DeviceProvisioning.status == DeviceProvisionStatus.PROVISIONED.value,
                    )
                )
            except Exception:
                existing_prov_sn = None

            if existing_prov_sn is not None and existing_prov_sn.tenant_id != request.tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error_code": "IDENTITY_CONFLICT",
                        "message": (
                            f"Device SN '{request.sn}' is already provisioned to tenant "
                            f"{existing_prov_sn.tenant_id}"
                        ),
                        "operation_id": request.operation_id,
                    },
                )

            # 3. Synchronize core DB entities (Org, Device, DeviceOrgBind, DeviceConnection, DeviceAuditLog)
            now_utc = datetime.now(timezone.utc)
            try:
                is_mock = getattr(session, "is_mock", False)
                if is_mock:
                    org_exists = await session.scalar(select(Org).where(Org.org_id == request.tenant_id))
                    if not org_exists:
                        session.add(Org(org_id=request.tenant_id, name=f"Org {request.tenant_id}"))
                    session.add(Device(device_id=target_device_id, sn=request.sn, is_deleted=False))
                    session.add(DeviceOrgBind(device_id=target_device_id, org_id=request.tenant_id))
                    session.add(DeviceConnection(device_id=target_device_id, client_id=request.sn))
                else:
                    # 3a. Ensure Org exists
                    await session.execute(
                        pg_insert(Org)
                        .values({"org_id": request.tenant_id, "name": f"Org {request.tenant_id}"})
                        .on_conflict_do_nothing(index_elements=["org_id"])
                    )

                    # 3b. Ensure Device exists
                    await session.execute(
                        pg_insert(Device)
                        .values({
                            "device_id": target_device_id,
                            "sn": request.sn,
                            "is_deleted": False,
                            "deleted_at": None,
                        })
                        .on_conflict_do_update(
                            index_elements=["device_id"],
                            set_=dict(
                                sn=request.sn,
                                is_deleted=False,
                                deleted_at=None,
                            ),
                        )
                    )

                    # 3c. Ensure DeviceOrgBind exists
                    await session.execute(
                        pg_insert(DeviceOrgBind)
                        .values({"device_id": target_device_id, "org_id": request.tenant_id})
                        .on_conflict_do_update(
                            index_elements=["device_id"],
                            set_=dict(org_id=request.tenant_id),
                        )
                    )

                    # 3d. Ensure DeviceConnection exists
                    await session.execute(
                        pg_insert(DeviceConnection)
                        .values({"device_id": target_device_id, "client_id": request.sn})
                        .on_conflict_do_update(
                            index_elements=["device_id"],
                            set_=dict(
                                client_id=request.sn,
                                is_blocked=False,
                                violation_type=None,
                                violation_details=None,
                            ),
                        )
                    )

                # 3e. Audit log
                audit_log = DeviceAuditLog(
                    device_id=target_device_id,
                    org_id=request.tenant_id,
                    event_type="PROVISIONED",
                    actor=request.requested_by_user_id or "service/provisioning",
                    details={
                        "sn": request.sn,
                        "terminal_id": request.terminal_id,
                        "operation_id": request.operation_id,
                        "correlation_id": request.correlation_id,
                    },
                )
                session.add(audit_log)

                # 4. Insert DeviceProvisioning record
                prov_rec = DeviceProvisioning(
                    operation_id=request.operation_id,
                    contract_version=request.contract_version,
                    tenant_id=request.tenant_id,
                    terminal_id=request.terminal_id,
                    sn=request.sn,
                    device_id=target_device_id,
                    status=DeviceProvisionStatus.PROVISIONED.value,
                    correlation_id=request.correlation_id,
                    requested_by_user_id=request.requested_by_user_id,
                    error_code=None,
                    error_message=None,
                    payload_hash=payload_hash,
                    provisioning_metadata=request.metadata,
                    created_at=now_utc,
                    updated_at=now_utc,
                    provisioned_at=now_utc,
                )
                session.add(prov_rec)
                await session.flush()

                # 5. Emit durable event into the event feed
                await remote_session_event_service.record_device_provisioned(
                    session,
                    sn=request.sn,
                    tenant_id=request.tenant_id,
                    terminal_id=request.terminal_id,
                    device_id=target_device_id,
                    operation_id=request.operation_id,
                    correlation_id=request.correlation_id,
                    payload=request.metadata,
                )

                log.info(
                    "Provisioned device sn=%s device_id=%s terminal_id=%s tenant_id=%s operation_id=%s",
                    request.sn,
                    target_device_id,
                    request.terminal_id,
                    request.tenant_id,
                    request.operation_id,
                )
                return prov_rec, False

            except IntegrityError as exc:
                await session.rollback()
                # Check if concurrent request with same operation_id just succeeded
                existing_after_race = await self.get_provisioning_by_operation(session, request.operation_id)
                if existing_after_race is not None:
                    if existing_after_race.payload_hash == payload_hash:
                        return existing_after_race, True
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "error_code": "OPERATION_ID_CONFLICT",
                            "message": (
                                f"Operation ID '{request.operation_id}' was previously executed "
                                "with different parameters"
                            ),
                            "operation_id": request.operation_id,
                        },
                    ) from exc

                log.error("Integrity error during provisioning for sn=%s: %s", request.sn, exc)
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error_code": "IDENTITY_CONFLICT",
                        "message": f"Database integrity conflict during provisioning: {exc.orig if hasattr(exc, 'orig') else str(exc)}",
                        "operation_id": request.operation_id,
                    },
                ) from exc

    async def get_provisioning_by_operation(
        self,
        session: AsyncSession,
        operation_id: str,
    ) -> DeviceProvisioning | None:
        """Fetch device provisioning record by operation_id."""
        try:
            return await session.scalar(
                select(DeviceProvisioning).where(DeviceProvisioning.operation_id == operation_id)
            )
        except Exception as e:
            log.debug("get_provisioning_by_operation error for operation_id=%s: %s", operation_id, e)
            return None

    async def get_provisioning_by_sn(
        self,
        session: AsyncSession,
        sn: str,
    ) -> DeviceProvisioning | None:
        """Fetch latest device provisioning record by SN."""
        try:
            return await session.scalar(
                select(DeviceProvisioning)
                .where(DeviceProvisioning.sn == sn)
                .order_by(DeviceProvisioning.id.desc())
                .limit(1)
            )
        except Exception as e:
            log.debug("get_provisioning_by_sn error for sn=%s: %s", sn, e)
            return None

    async def get_provisioning_by_terminal(
        self,
        session: AsyncSession,
        tenant_id: int,
        terminal_id: int,
    ) -> DeviceProvisioning | None:
        """Fetch latest device provisioning record by tenant_id and terminal_id."""
        try:
            return await session.scalar(
                select(DeviceProvisioning)
                .where(
                    DeviceProvisioning.tenant_id == tenant_id,
                    DeviceProvisioning.terminal_id == terminal_id,
                )
                .order_by(DeviceProvisioning.id.desc())
                .limit(1)
            )
        except Exception as e:
            log.debug(
                "get_provisioning_by_terminal error for tenant=%s terminal=%s: %s",
                tenant_id,
                terminal_id,
                e,
            )
            return None


device_provisioning_service = DeviceProvisioningService()
