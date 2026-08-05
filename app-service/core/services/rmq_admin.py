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
        device_names = [name for name in await DeviceRepo.list(session) if name]
        if not device_names:
            return None

        # Always reconcile every device from DB, not only missing RabbitMQ users.
        # This restores permissions/topic-permissions after RabbitMQ definitions or ACL loss.
        return await RmqAdminApi.set_device_definitions(device_names, dry_run=dry_run)
