import asyncio
import logging

import httpx

from core import settings
from core.schemas.rmq_admin import DeviceConnectionDetails

log = logging.getLogger(__name__)


async def fetch_one(session, suffix, param):
    params = suffix + param
    resp = await session.get(url=params)
    resp.raise_for_status()  # Проверка на наличие ошибок HTTP
    return resp


class RmqAdminApi:
    user_conn = "api/connections/username/"
    conn = "api/connections/"

    # @classmethod
    # async def session_getter(cls):
    #     return httpx.AsyncClient(base_url=str(settings.leo4.admin_url))

    @classmethod
    async def get_connection(cls, sn_arr):
        try:

            # async with httpx.AsyncClient(base_url=str(settings.leo4.admin_url)) as session:
            async with httpx.AsyncClient(
                base_url=str(settings.leo4.admin_url)
            ) as session:
                tasks = [fetch_one(session, cls.user_conn, sn) for sn in sn_arr]
                connections = await asyncio.gather(*tasks)
                tasks1 = []
                for conn in connections:
                    data = conn.json()
                    if len(data) > 0:
                        tasks1.append(fetch_one(session, cls.conn, data[0]["name"]))
                device_online = await asyncio.gather(*tasks1)
            devices: list[DeviceConnectionDetails] = [
                DeviceConnectionDetails.model_validate(device.json())
                for device in device_online
            ]
            return devices
        except Exception as e:
            log.info("Error Get connectionsFrom rabbit API =%s", e)
            return None


# DeviceConnectionDetails
