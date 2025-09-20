import logging
from sqlalchemy.ext.asyncio import AsyncSession
from core.crud.device_repo import DeviceRepo
from core.integrations.rmq_admin_api import RmqAdminApi
from core.integrations.ya_leo4_cloud import get_factory_device_list


log = logging.getLogger(__name__)


class RmqAdmin:
    @classmethod
    def __init__(cls):
        pass

    @classmethod
    async def get_online_devices(cls, sn_arr):
        devs_online = await RmqAdminApi.get_connection(sn_arr)
        return devs_online

    @classmethod
    async def repl_devices(cls, session: AsyncSession, api_key: str):
        da = await get_factory_device_list(api_key)
        if da:
            await DeviceRepo.add_devices(session, da)
        return da

    @classmethod
    async def set_device_definitions(cls, session: AsyncSession):
        names = await RmqAdminApi.get_exist_devices()
        if names:
            lu1 = await DeviceRepo.get_exist_device_sn(session, names)
            # defns = {"users": [], "permissions": []}
            if lu1:
                await RmqAdminApi.set_device_definitions(lu1)
