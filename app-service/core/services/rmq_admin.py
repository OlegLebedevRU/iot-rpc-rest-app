from sqlalchemy.ext.asyncio import AsyncSession
from core.crud.device_repo import DeviceRepo
from core.integrations.rmq_admin_api import RmqAdminApi
from core.integrations.ya_leo4_cloud import get_factory_device_list


class RmqAdmin:
    @classmethod
    def __init__(cls):
        pass

    @classmethod
    async def get_online_devices(cls, sn_arr):
        devs_online = await RmqAdminApi.get_connection(sn_arr)
        return devs_online

    @classmethod
    async def repl_devices(
        cls, session: AsyncSession, api_key: str, dry_run: bool = False
    ):
        da = await get_factory_device_list(api_key)
        if da and not dry_run:
            await DeviceRepo.add_devices(session, da)
        return da

    @classmethod
    async def set_device_definitions(cls, session: AsyncSession, dry_run: bool = False):
        blocked_names = set(filter(None, await DeviceRepo.list_blocked(session)))
        device_names = [
            name
            for name in await DeviceRepo.list(session)
            if name and name not in blocked_names
        ]

        # Always reconcile baseline service definitions (etran_service, etc.)
        await RmqAdminApi.reconcile_service_definitions(dry_run=dry_run)

        if not device_names and not blocked_names:
            return None

        # Revoke first: an inconsistent duplicate SN must never be restored below.
        blocked_errors = []
        if not dry_run:
            for name in sorted(blocked_names):
                if not await RmqAdminApi.block_device_user(name):
                    blocked_errors.append(
                        {"device": name, "error": "delete_user_failed"}
                    )

        # Full reconciliation is limited to startup and explicit recovery. Normal
        # provisioning calls RmqAdminApi for the requested SNs only.
        result = await RmqAdminApi.set_device_definitions(device_names, dry_run=dry_run)
        result["blocked_deleted"] = (
            0 if dry_run else len(blocked_names) - len(blocked_errors)
        )
        result["blocked_would_delete"] = len(blocked_names) if dry_run else 0
        result["errors"].extend(blocked_errors)
        return result
