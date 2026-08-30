from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from core.crud.device_repo import DeviceRepo
from core.integrations.rmq_admin_api import RmqAdminApi
from core.logging_config import setup_module_logger
from core.schemas.provisioning import (
    OrgApiKeyProvisionRequest,
    OrgApiKeyResponse,
    TerminalProvisionRequest,
    TerminalProvisionResult,
    TerminalStatusResult,
)
from core.services.devices import clear_device_connection_history

log = setup_module_logger(__name__, "srv_provisioning.log")


class ProvisioningService:
    @classmethod
    async def provision_terminals(
        cls,
        session: AsyncSession,
        terminals: list[TerminalProvisionRequest],
    ) -> list[TerminalProvisionResult]:
        if not terminals:
            return []

        # 1. Prepare data for DB
        terminals_data: list[dict[str, Any]] = [
            {
                "device_id": t.device_id,
                "sn": t.sn,
                "org_id": t.org_id,
                "name": t.name,
                "tags": t.tags,
            }
            for t in terminals
        ]

        # 2. Persist to DB
        try:
            await DeviceRepo.provision_terminals(session, terminals_data)
        except Exception as e:
            log.exception("Error persisting provisioned terminals to DB: %s", e)
            return [
                TerminalProvisionResult(
                    device_id=t.device_id,
                    sn=t.sn,
                    org_id=t.org_id,
                    success=False,
                    rmq_user_status="error",
                    is_online=False,
                    error=f"Database error: {e}",
                )
                for t in terminals
            ]

        # 3. Configure RabbitMQ users and topic permissions
        sns = [t.sn for t in terminals]
        rmq_res = None
        try:
            rmq_res = await RmqAdminApi.set_device_definitions(sns)
            log.info("RabbitMQ definitions result for provisioned devices: %s", rmq_res)
        except Exception as e:
            log.exception("Error configuring RabbitMQ definitions: %s", e)

        # 4. Check active connections
        online_devices_map: dict[str, Any] = {}
        try:
            devs_online = await RmqAdminApi.get_connection(sns)
            for d in devs_online:
                if d and hasattr(d, "user") and d.user:
                    online_devices_map[d.user] = d
        except Exception as e:
            log.info("Could not fetch connection status during provisioning: %s", e)

        # 5. Build results and clear collision history
        results: list[TerminalProvisionResult] = []
        for t in terminals:
            clear_device_connection_history(t.sn)
            online_info = online_devices_map.get(t.sn)
            is_online = online_info is not None
            conn_at = None
            if online_info and getattr(online_info, "connected_at", None):
                from datetime import datetime, UTC
                conn_at = datetime.fromtimestamp(online_info.connected_at / 1000, tz=UTC)

            rmq_status = "ok" if rmq_res and not rmq_res.get("errors") else "rmq_warning"
            results.append(
                TerminalProvisionResult(
                    device_id=t.device_id,
                    sn=t.sn,
                    org_id=t.org_id,
                    success=True,
                    rmq_user_status=rmq_status,
                    is_online=is_online,
                    connected_at=conn_at,
                    error=None,
                )
            )
        return results

    @classmethod
    async def get_terminals_status(
        cls,
        session: AsyncSession,
        device_ids: list[int],
    ) -> list[TerminalStatusResult]:
        raw_statuses = await DeviceRepo.get_terminals_status_by_device_ids(
            session, device_ids
        )
        return [
            TerminalStatusResult(
                device_id=s["device_id"],
                sn=s["sn"],
                org_id=s["org_id"],
                is_provisioned=s["is_provisioned"],
                is_online=s["is_online"],
                connected_at=s["connected_at"],
                checked_at=s["checked_at"],
            )
            for s in raw_statuses
        ]

    @classmethod
    def mask_api_key(cls, key: str) -> str:
        if not key:
            return ""
        if len(key) <= 8:
            return "*" * (len(key) - 2) + key[-2:] if len(key) > 2 else "*" * len(key)
        return key[:4] + "*" * (len(key) - 8) + key[-4:]

    @classmethod
    async def provision_org_api_key(
        cls,
        session: AsyncSession,
        request: OrgApiKeyProvisionRequest,
    ) -> OrgApiKeyResponse:
        from core.models import Org, OrgApiKey
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy import select, func
        from fastapi import HTTPException, status

        existing_key_owner = await session.scalar(
            select(OrgApiKey.org_id).where(
                OrgApiKey.api_key == request.api_key,
                OrgApiKey.org_id != request.org_id,
            )
        )
        if existing_key_owner is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"API key is already assigned to organization {existing_key_owner}",
            )

        # Ensure parent Org exists in tb_orgs
        await session.execute(
            pg_insert(Org)
            .values({"org_id": request.org_id, "name": request.name or f"Org {request.org_id}", "is_deleted": False})
            .on_conflict_do_nothing(index_elements=["org_id"])
        )

        stmt = (
            pg_insert(OrgApiKey)
            .values(
                {
                    "org_id": request.org_id,
                    "api_key": request.api_key,
                    "name": request.name,
                    "is_active": request.is_active,
                }
            )
            .on_conflict_do_update(
                index_elements=["org_id"],
                set_={
                    "api_key": request.api_key,
                    "name": request.name,
                    "is_active": request.is_active,
                    "updated_at": func.current_timestamp(),
                },
            )
            .returning(OrgApiKey)
        )
        result = await session.scalar(stmt)
        await session.commit()
        return OrgApiKeyResponse(
            org_id=result.org_id,
            api_key=result.api_key,
            name=result.name,
            is_active=result.is_active,
            created_at=result.created_at,
            updated_at=result.updated_at,
        )

    @classmethod
    async def get_org_api_key(
        cls,
        session: AsyncSession,
        org_id: int,
        mask: bool = False,
    ) -> OrgApiKeyResponse | None:
        from core.models import OrgApiKey
        from sqlalchemy import select

        stmt = select(OrgApiKey).where(OrgApiKey.org_id == org_id)
        record = await session.scalar(stmt)
        if record is None:
            return None
        return OrgApiKeyResponse(
            org_id=record.org_id,
            api_key=cls.mask_api_key(record.api_key) if mask else record.api_key,
            name=record.name,
            is_active=record.is_active,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @classmethod
    async def delete_org_api_key(
        cls,
        session: AsyncSession,
        org_id: int,
    ) -> bool:
        from core.models import OrgApiKey
        from sqlalchemy import delete

        stmt = delete(OrgApiKey).where(OrgApiKey.org_id == org_id)
        result = await session.execute(stmt)
        await session.commit()
        return bool(result.rowcount and result.rowcount > 0)
