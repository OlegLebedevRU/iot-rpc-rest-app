from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from core.crud.device_repo import DeviceRepo
from core.integrations.rmq_admin_api import RmqAdminApi
from core.logging_config import setup_module_logger
from core.schemas.provisioning import (
    TerminalProvisionRequest,
    TerminalProvisionResult,
    TerminalStatusResult,
)

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

        # 5. Build results
        results: list[TerminalProvisionResult] = []
        for t in terminals:
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
