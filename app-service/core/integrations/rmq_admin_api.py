import asyncio
import logging
from urllib.parse import quote, urljoin

from core.logging_config import setup_module_logger
import httpx
from core import settings
from core.schemas.rmq_admin import DeviceConnectionDetails

# Отключаем подробное логирование HTTP-запросов от httpx
logging.getLogger("httpx").setLevel(logging.WARNING)
# ogging.getLogger("httpx._client").setLevel(logging.WARNING)

log = setup_module_logger(__name__, "rabbit_admin_api.log")


async def fetch_one(session, suffix, param):
    params = suffix + quote(param, safe="")
    resp = await session.get(url=params)
    if resp.status_code == 404:
        return []
    resp.raise_for_status()  # Проверка на наличие ошибок HTTP
    return resp.json()


class RmqAdminApi:
    user_conn = "api/connections/username/"
    conn = "api/connections/"

    _vhost = "/"
    _exchange = "amq.topic"

    @staticmethod
    def _admin_url(path: str = "") -> str:
        base_url = str(settings.leo4.admin_url)
        if not base_url.endswith("/"):
            base_url += "/"
        return urljoin(base_url, path)

    @staticmethod
    def _quote_path(value: str) -> str:
        return quote(value, safe="")

    @staticmethod
    def _user_payload(name: str) -> dict:
        return {
            "password_hash": "",
            "hashing_algorithm": "rabbit_password_hashing_sha256",
            "tags": "device",
        }

    @classmethod
    def _permission_payload(cls) -> dict:
        return {
            "configure": ".*",
            "write": ".*",
            "read": ".*",
        }

    @classmethod
    def _topic_permission_payload(cls) -> dict:
        return {
            "exchange": cls._exchange,
            "write": "^dev.{client_id}.*",
            "read": "^srv.{client_id}.*",
        }

    @staticmethod
    def _same_permissions(existing: dict | None, expected: dict) -> bool:
        if not isinstance(existing, dict):
            return False
        return (
            existing.get("configure") == expected["configure"]
            and existing.get("write") == expected["write"]
            and existing.get("read") == expected["read"]
        )

    @classmethod
    def _same_topic_permissions(cls, existing: dict | list | None, expected: dict) -> bool:
        if isinstance(existing, list):
            existing = next(
                (item for item in existing if item.get("exchange") == cls._exchange), None
            )
        if not isinstance(existing, dict):
            return False
        return (
            existing.get("exchange") == expected["exchange"]
            and existing.get("write") == expected["write"]
            and existing.get("read") == expected["read"]
        )

    @staticmethod
    async def _get_json_or_none(client: httpx.AsyncClient, path: str):
        response = await client.get(path)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    @classmethod
    async def get_connection(cls, sn_arr):
        try:
            async with httpx.AsyncClient(base_url=cls._admin_url()) as session:
                tasks = [fetch_one(session, cls.user_conn, sn) for sn in sn_arr]
                connections = await asyncio.gather(*tasks, return_exceptions=True)

            devices: list[DeviceConnectionDetails] = []
            for sn, conn_data in zip(sn_arr, connections, strict=False):
                if isinstance(conn_data, Exception):
                    log.info("Error Get connectionsFrom rabbit API for '%s' = %s", sn, conn_data)
                    continue

                if not isinstance(conn_data, list):
                    log.info(
                        "Unexpected RabbitMQ connections payload for '%s': %s",
                        sn,
                        type(conn_data).__name__,
                    )
                    continue

                for device in conn_data:
                    try:
                        devices.append(DeviceConnectionDetails.model_validate(device))
                    except Exception as e:
                        log.info(
                            "Skip invalid RabbitMQ connection payload for '%s': %s; payload=%s",
                            sn,
                            e,
                            device,
                        )
            return devices
        except Exception as e:
            log.info("Error Get connectionsFrom rabbit API =%s", e)
            return []

    @classmethod
    async def get_exist_devices(cls):
        try:
            async with httpx.AsyncClient(base_url=cls._admin_url()) as client:
                r = await client.get("api/users")
                r.raise_for_status()
            log.info("admin - get_u, body =%s", str(r))
            n_obj = r.json()
            names = [""]
            for u in n_obj:
                names.append(u["name"])
            return names
        except Exception as e:
            log.info("admin - get_u error =%s", e)
            return [""]

    @classmethod
    async def set_device_definitions(cls, lu1, dry_run: bool = False):
        if not lu1:
            return {
                "created": 0,
                "updated": 0,
                "skipped": 0,
                "would_create": 0,
                "would_update": 0,
                "errors": [],
            }

        result = {
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "would_create": 0,
            "would_update": 0,
            "errors": [],
        }
        vhost_quoted = cls._quote_path(cls._vhost)

        async with httpx.AsyncClient(base_url=cls._admin_url(), timeout=10.0) as client:
            for device_name in lu1:
                user_quoted = cls._quote_path(device_name)
                perm_payload = cls._permission_payload()
                topic_payload = cls._topic_permission_payload()

                try:
                    # Пользователя создаем только если его еще нет: это безопаснее, чем bulk replace definitions.
                    user = await cls._get_json_or_none(client, f"api/users/{user_quoted}")
                    if user is None:
                        if dry_run:
                            result["would_create"] += 1
                        else:
                            create_user = await client.put(
                                f"api/users/{user_quoted}", json=cls._user_payload(device_name)
                            )
                            create_user.raise_for_status()
                            result["created"] += 1
                    else:
                        result["skipped"] += 1

                    existing_perm = await cls._get_json_or_none(
                        client, f"api/permissions/{vhost_quoted}/{user_quoted}"
                    )
                    if not cls._same_permissions(existing_perm, perm_payload):
                        if dry_run:
                            result["would_update"] += 1
                        else:
                            upsert_perm = await client.put(
                                f"api/permissions/{vhost_quoted}/{user_quoted}",
                                json=perm_payload,
                            )
                            upsert_perm.raise_for_status()
                            result["updated"] += 1

                    existing_topic_perm = await cls._get_json_or_none(
                        client, f"api/topic-permissions/{vhost_quoted}/{user_quoted}"
                    )
                    if not cls._same_topic_permissions(existing_topic_perm, topic_payload):
                        if dry_run:
                            result["would_update"] += 1
                        else:
                            upsert_topic_perm = await client.put(
                                f"api/topic-permissions/{vhost_quoted}/{user_quoted}",
                                json=topic_payload,
                            )
                            upsert_topic_perm.raise_for_status()
                            result["updated"] += 1
                except Exception as e:
                    result["errors"].append({"device": device_name, "error": str(e)})
                    log.info("RMQ incremental definitions error for '%s': %s", device_name, e)

        mode = "dry-run" if dry_run else "apply"
        log.info("set RMQ definitions incrementally (%s) = %s", mode, result)
        return result
