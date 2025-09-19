import logging

import httpx
from fastapi import HTTPException
from sqlalchemy import select, not_
from sqlalchemy.ext.asyncio import AsyncSession

from core import settings
from core.crud.administrator import AdminRepo
from core.crud.device_repo import DeviceRepo
from core.integrations.rmq_admin_api import RmqAdminApi
from core.integrations.ya_leo4_cloud import get_factory_device_list
from core.models import Device

log = logging.getLogger(__name__)


class RmqAdmin:
    @classmethod
    def __init__(cls):
        pass

    @classmethod
    async def get_online_devices(cls, sn_arr):
        return await RmqAdminApi.get_connection(sn_arr)

    @classmethod
    async def repl_devices(cls, session: AsyncSession, api_key: str):
        da = await get_factory_device_list(api_key)
        await AdminRepo.add_devices(session, da)
        # print(do_nothing_stmt)
        return da

    @classmethod
    async def set_device_definitions(cls, session: AsyncSession):
        names = await RmqAdminApi.get_exist_devices()
        lu1 = await DeviceRepo.det_exist_device_sn(session, names)
        # defns = {"users": [], "permissions": []}
        await RmqAdminApi.set_device_definitions(lu1)
