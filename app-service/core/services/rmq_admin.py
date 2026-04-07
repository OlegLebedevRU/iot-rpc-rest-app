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
    async def repl_devices(cls, session: AsyncSession, api_key: str, dry_run: bool = False):
        da = await get_factory_device_list(api_key)
        if da and not dry_run:
            await DeviceRepo.add_devices(session, da)
        return da

    @classmethod
    async def set_device_definitions(cls, session: AsyncSession, dry_run: bool = False):
        names = await RmqAdminApi.get_exist_devices()
        result = None
        if names:
            lu1 = await DeviceRepo.find_missing_devices(session, names)
            # defns = {"users": [], "permissions": []}
            if lu1:
                result = await RmqAdminApi.set_device_definitions(lu1, dry_run=dry_run)
        return result
