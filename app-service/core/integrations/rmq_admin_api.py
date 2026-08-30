import asyncio
import logging
import time
from typing import Any
from urllib.parse import quote, urljoin

from core.logging_config import setup_module_logger
import httpx
from core import settings
from core.schemas.rmq_admin import DeviceConnectionDetails

# Отключаем подробное логирование HTTP-запросов от httpx
logging.getLogger("httpx").setLevel(logging.WARNING)
# ogging.getLogger("httpx._client").setLevel(logging.WARNING)

log = setup_module_logger(__name__, "rabbit_admin_api.log")

IGNORED_USERS: frozenset[str] = frozenset(
    {"guest", "admin", "user", "internal", "root", "anonymous", "null", "none"}
)


def extract_device_sn_from_conn(conn_data: dict[str, Any]) -> str | None:
    """Извлекает серийный номер устройства из данных соединения RabbitMQ."""
    user = conn_data.get("user")
    if user and isinstance(user, str) and user.strip().lower() not in IGNORED_USERS:
        return user.strip()

    client_props = conn_data.get("client_properties")
    if isinstance(client_props, dict):
        client_id = client_props.get("client_id")
        if (
            client_id
            and isinstance(client_id, str)
            and client_id.strip().lower() not in IGNORED_USERS
        ):
            return client_id.strip()

    return None


async def fetch_one(session, suffix, param):
    params = suffix + quote(param, safe="")
    resp = await session.get(url=params)
    if resp.status_code == 404:
        return None
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
    async def get_single_connection_details(
        cls,
        conn_name: str | None = None,
        sn: str | None = None,
        timeout_sec: float = 2.0,
    ) -> dict[str, Any] | None:
        """Получает детальную информацию об одном соединении из RabbitMQ Management API."""
        if not conn_name and not sn:
            return None

        url = cls._admin_url()
        try:
            timeout = httpx.Timeout(timeout_sec, connect=min(1.5, timeout_sec))
            async with httpx.AsyncClient(base_url=url, timeout=timeout) as client:
                if conn_name:
                    data = await cls._get_json_or_none(
                        client, f"api/connections/{cls._quote_path(conn_name)}"
                    )
                    if isinstance(data, dict) and data:
                        return data

                if sn:
                    user_quoted = cls._quote_path(sn)
                    conns = await cls._get_json_or_none(
                        client, f"api/connections/username/{user_quoted}"
                    )
                    if isinstance(conns, list) and conns:
                        target_conn = conns[-1]
                        target_name = (
                            target_conn.get("name")
                            if isinstance(target_conn, dict)
                            else None
                        )
                        if target_name:
                            data = await cls._get_json_or_none(
                                client,
                                f"api/connections/{cls._quote_path(target_name)}",
                            )
                            if isinstance(data, dict) and data:
                                return data
                        if isinstance(target_conn, dict):
                            return target_conn
        except Exception as exc:
            log.warning(
                "Failed to fetch single connection details from RMQ API (conn_name=%s, sn=%s): %s",
                conn_name,
                sn,
                exc,
            )

        return None

    @classmethod
    async def get_all_connections(
        cls,
        time_budget_sec: float = 10.0,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """Получает список всех активных соединений из RabbitMQ Management API
        с контролем временного бюджета и порционной загрузкой при необходимости.
        """
        start_time = time.monotonic()
        url = cls._admin_url()
        all_connections: list[dict[str, Any]] = []

        try:
            timeout = httpx.Timeout(min(time_budget_sec, 10.0), connect=5.0)
            async with httpx.AsyncClient(base_url=url, timeout=timeout) as client:
                page = 1
                while True:
                    elapsed = time.monotonic() - start_time
                    remaining_budget = time_budget_sec - elapsed
                    if remaining_budget <= 0.5:
                        log.warning(
                            "Time budget exhausted while fetching RMQ connections (elapsed=%.2fs, budget=%.2fs). Collected %d connections so far.",
                            elapsed,
                            time_budget_sec,
                            len(all_connections),
                        )
                        break

                    try:
                        resp = await client.get(
                            "api/connections",
                            params={
                                "page": page,
                                "page_size": page_size,
                                "pagination": "true",
                            },
                        )
                    except Exception as e:
                        log.warning("HTTP error querying api/connections: %s", e)
                        break

                    if resp.status_code != 200:
                        if page == 1:
                            try:
                                fallback_resp = await client.get("api/connections")
                                if fallback_resp.status_code == 200:
                                    data = fallback_resp.json()
                                    if isinstance(data, list):
                                        return data
                            except Exception as e:
                                log.warning("HTTP fallback query error: %s", e)
                        log.warning("Failed to fetch RMQ connections: status=%d", resp.status_code)
                        break

                    data = resp.json()
                    if isinstance(data, dict) and "items" in data:
                        items = data.get("items", [])
                        all_connections.extend(items)
                        page_count = data.get("page_count", 1)
                        if page >= page_count or not items:
                            break
                        page += 1
                    elif isinstance(data, list):
                        all_connections.extend(data)
                        break
                    else:
                        break

                    await asyncio.sleep(0.01)

        except Exception as exc:
            log.warning("Exception while fetching RMQ connections: %s", exc)

        return all_connections

    @classmethod
    async def get_connection(cls, sn_arr):
        try:
            async with httpx.AsyncClient(base_url=cls._admin_url()) as session:
                tasks = [fetch_one(session, cls.user_conn, sn) for sn in sn_arr]
                connections = await asyncio.gather(*tasks, return_exceptions=True)

                detail_requests: list[tuple[str, str, asyncio.Future]] = []
                for sn, conn_data in zip(sn_arr, connections, strict=False):
                    if isinstance(conn_data, Exception):
                        log.info("Error Get connectionsFrom rabbit API for '%s' = %s", sn, conn_data)
                        continue

                    if conn_data is None:
                        continue

                    if not isinstance(conn_data, list):
                        log.info(
                            "Unexpected RabbitMQ connections payload for '%s': %s",
                            sn,
                            type(conn_data).__name__,
                        )
                        continue

                    for device in conn_data:
                        connection_name = device.get("name")
                        if not connection_name:
                            log.info(
                                "RabbitMQ connection summary for '%s' has no name: payload=%s",
                                sn,
                                device,
                            )
                            continue
                        detail_requests.append(
                            (sn, connection_name, fetch_one(session, cls.conn, connection_name))
                        )

                detail_results = await asyncio.gather(
                    *(request for _, _, request in detail_requests),
                    return_exceptions=True,
                )

            devices: list[DeviceConnectionDetails] = []
            for (sn, connection_name, _), conn_data in zip(
                detail_requests, detail_results, strict=False
            ):
                if isinstance(conn_data, Exception):
                    log.info(
                        "Error Get connection details from rabbit API for '%s' (%s) = %s",
                        sn,
                        connection_name,
                        conn_data,
                    )
                    continue

                if conn_data is None:
                    log.info(
                        "RabbitMQ connection disappeared before details fetch for '%s': %s",
                        sn,
                        connection_name,
                    )
                    continue

                try:
                    devices.append(DeviceConnectionDetails.model_validate(conn_data))
                except Exception as e:
                    log.info(
                        "Skip invalid RabbitMQ connection payload for '%s': %s; payload=%s",
                        sn,
                        e,
                        conn_data,
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

    @classmethod
    async def terminate_connection(cls, conn_name: str) -> bool:
        """Принудительно закрывает соединение в RabbitMQ по имени сокета."""
        if not conn_name:
            return False
        try:
            conn_quoted = cls._quote_path(conn_name)
            async with httpx.AsyncClient(base_url=cls._admin_url(), timeout=5.0) as client:
                resp = await client.delete(f"api/connections/{conn_quoted}")
                if resp.status_code in (200, 204, 404):
                    log.info("Terminated RMQ connection %s (status=%s)", conn_name, resp.status_code)
                    return True
                resp.raise_for_status()
                return True
        except Exception as e:
            log.warning("Failed to terminate RMQ connection %s: %s", conn_name, e)
            return False

    @classmethod
    async def terminate_user_connections(cls, username: str) -> int:
        """Принудительно закрывает все активные соединения указанного пользователя."""
        if not username:
            return 0
        terminated_count = 0
        try:
            user_quoted = cls._quote_path(username)
            async with httpx.AsyncClient(base_url=cls._admin_url(), timeout=5.0) as client:
                conns = await cls._get_json_or_none(client, f"api/connections/username/{user_quoted}")
                if isinstance(conns, list):
                    for conn in conns:
                        if isinstance(conn, dict):
                            name = conn.get("name")
                            if name:
                                resp = await client.delete(f"api/connections/{cls._quote_path(name)}")
                                if resp.status_code in (200, 204, 404):
                                    terminated_count += 1
            log.info("Terminated %d connections for user %s", terminated_count, username)
        except Exception as e:
            log.warning("Failed to terminate user connections for %s: %s", username, e)
        return terminated_count

    @classmethod
    async def block_device_user(cls, username: str) -> bool:
        """Блокирует устройство в RabbitMQ: обнуляет права и принудительно сбрасывает сокеты."""
        if not username:
            return False
        vhost_quoted = cls._quote_path(cls._vhost)
        user_quoted = cls._quote_path(username)
        block_perm = {"configure": "^$", "write": "^$", "read": "^$"}
        try:
            async with httpx.AsyncClient(base_url=cls._admin_url(), timeout=5.0) as client:
                # 1. Revoke vhost permissions
                resp = await client.put(
                    f"api/permissions/{vhost_quoted}/{user_quoted}",
                    json=block_perm,
                )
                resp.raise_for_status()

                # 2. Clear topic permissions
                try:
                    await client.delete(f"api/topic-permissions/{vhost_quoted}/{user_quoted}")
                except Exception:
                    pass

            # 3. Kill active connections
            await cls.terminate_user_connections(username)
            log.info("Successfully blocked device user %s in RabbitMQ", username)
            return True
        except Exception as e:
            log.warning("Failed to block device user %s in RabbitMQ: %s", username, e)
            return False

    @classmethod
    async def unblock_device_user(cls, username: str) -> bool:
        """Разблокирует устройство в RabbitMQ: восстанавливает стандартные права доступа."""
        if not username:
            return False
        vhost_quoted = cls._quote_path(cls._vhost)
        user_quoted = cls._quote_path(username)
        perm_payload = cls._permission_payload()
        topic_payload = cls._topic_permission_payload()
        try:
            async with httpx.AsyncClient(base_url=cls._admin_url(), timeout=5.0) as client:
                # 1. Ensure user exists
                user = await cls._get_json_or_none(client, f"api/users/{user_quoted}")
                if user is None:
                    create_resp = await client.put(
                        f"api/users/{user_quoted}",
                        json=cls._user_payload(username),
                    )
                    create_resp.raise_for_status()

                # 2. Restore vhost permissions
                perm_resp = await client.put(
                    f"api/permissions/{vhost_quoted}/{user_quoted}",
                    json=perm_payload,
                )
                perm_resp.raise_for_status()

                # 3. Restore topic permissions
                topic_resp = await client.put(
                    f"api/topic-permissions/{vhost_quoted}/{user_quoted}",
                    json=topic_payload,
                )
                topic_resp.raise_for_status()

            log.info("Successfully unblocked device user %s in RabbitMQ", username)
            return True
        except Exception as e:
            log.warning("Failed to unblock device user %s in RabbitMQ: %s", username, e)
            return False
