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

    @classmethod
    async def get_connection(cls, sn_arr):
        try:
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

    @classmethod
    async def get_exist_devices(cls):
        r = httpx.get(url=str(settings.leo4.admin_url) + "api/users")
        log.info("admin - get_u, body =%s", str(r))
        names = [""]
        n_obj = r.json()
        print(n_obj)
        for u in n_obj:
            names.append(u["name"])
        return names

    @classmethod
    async def set_device_definitions(cls, lu1):
        d_users = []
        d_perm = []
        d_topic_perm = []
        for d in lu1:
            d_users.append(
                {
                    "name": d,
                    "password_hash": "",
                    "hashing_algorithm": "rabbit_password_hashing_sha256",
                    "tags": ["device"],
                    "limits": {},
                }
            )
            d_perm.append(
                {
                    "user": d,
                    "vhost": "/",
                    "configure": ".*",
                    "write": ".*",
                    "read": ".*",
                }
            )
            d_topic_perm.append(
                {
                    "user": d,
                    "vhost": "/",
                    "exchange": "amq.topic",
                    "write": "^dev.{client_id}.*",
                    "read": "^srv.{client_id}.*",
                }
            )
        defns = {}
        defns["users"] = d_users
        defns["permissions"] = d_perm
        defns["topic_permissions"] = d_topic_perm
        log.info("set RMQ definitions = %s", defns)

        r = httpx.post(
            url=str(settings.leo4.admin_url) + "api/definitions",
            json=defns,
            headers={"Content-type": "application/json"},
        )
        log.info("to rabbitmq api post definitions, status code= ", r.status_code)
