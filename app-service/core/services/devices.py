import asyncio
import time
from datetime import datetime, timezone
from collections import deque
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core import settings
from core.crud.device_repo import DeviceRepo
from core.integrations.rmq_admin_api import (
    RmqAdminApi,
    extract_device_sn_from_conn,
    is_ignored_or_service_identity,
    IGNORED_USERS,
)
from core.logging_config import setup_module_logger
from core.schemas.devices import DeviceConnectStatus, DeviceTagPut
from core.services.rmq_admin import RmqAdmin

log = setup_module_logger(__name__, "srv_devices.log")


@dataclass
class ConnectionSample:
    timestamp: float
    peer_host: str | None
    peer_port: int | None
    cert_validity: str | None
    conn_name: str | None


# Скользящее окно сэмплов подключений по SN (in-memory, до 30 сэмплов на устройство)
_device_connection_samples: dict[str, deque[ConnectionSample]] = {}


def clear_device_connection_history(sn: str | None = None) -> None:
    """Очищает историю сэмплов подключений для устройства (или для всех)."""
    if sn:
        _device_connection_samples.pop(sn, None)
    else:
        _device_connection_samples.clear()


def normalize_host(peer_host: Any, conn_name: str | None = None) -> str:
    """Нормализует host / IP в строковый вид."""
    if peer_host:
        return str(peer_host).strip()
    if conn_name and "->" in conn_name:
        src = conn_name.split("->")[0].strip()
        if ":" in src:
            return src.split(":")[0].strip()
        return src
    return ""


def evaluate_connection_collision(
    sn: str,
    peer_host: Any,
    peer_port: int | None,
    cert_validity: str | None,
    conn_name: str | None,
    now_ts: float | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    """Анализирует историю подключений устройства и определяет наличие коллизии.

    Дифференцирует:
    1) SN_COLLISION: одинаковый SN, но несовпадающие сроки/отпечатки сертификатов (мгновенная реакция).
    2) DEVICE_CLONE: одинаковый SN и сертификат, но скачки по любым разным IP-адресам
       (многооконный фильтр: >= 3 подключений за 180с и >= 2 смен хостов).
    """
    if not sn or is_ignored_or_service_identity(sn):
        return None, None

    if now_ts is None:
        now_ts = time.time()

    if sn not in _device_connection_samples:
        _device_connection_samples[sn] = deque(maxlen=30)

    history = _device_connection_samples[sn]

    # Очищаем устаревшие сэмплы старше 180 секунд (3 окна по 60с)
    cutoff = now_ts - 180.0
    while history and history[0].timestamp < cutoff:
        history.popleft()

    host_str = normalize_host(peer_host, conn_name)
    sample = ConnectionSample(
        timestamp=now_ts,
        peer_host=host_str or None,
        peer_port=peer_port,
        cert_validity=cert_validity.strip() if cert_validity else None,
        conn_name=conn_name,
    )
    history.append(sample)

    if len(history) < 2:
        return None, None

    # 1. Проверка SN_COLLISION (одинаковый SN, но разные валидные сертификаты)
    certs_in_window = {
        s.cert_validity for s in history if s.cert_validity is not None
    }
    if len(certs_in_window) >= 2:
        conflicting_hosts = sorted(
            list({s.peer_host for s in history if s.peer_host})
        )
        violation_details = {
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "violation_type": "SN_COLLISION",
            "cert_validities": sorted(list(certs_in_window)),
            "conflicting_hosts": conflicting_hosts,
            "flapping_count": len(history),
            "reason": "Multiple conflicting TLS certificates active for the same SN",
        }
        return "SN_COLLISION", violation_details

    # 2. Проверка DEVICE_CLONE (одинаковый SN и сертификат, но скачки по любым разным IP)
    # Защита от ложных срабатываний: требуется не менее 3 подключений за скользящее окно (180 сек)
    # с минимум 2 различными IP-адресами и быстрыми переключениями (flapping >= 2 смен хостов).
    if len(history) >= 3:
        valid_hosts = [s.peer_host for s in history if s.peer_host]
        unique_hosts = set(valid_hosts)
        if len(unique_hosts) >= 2:
            host_switches = 0
            for i in range(1, len(history)):
                h_prev = history[i - 1].peer_host
                h_curr = history[i].peer_host
                if h_prev and h_curr and h_prev != h_curr:
                    host_switches += 1

            if host_switches >= 2:
                violation_details = {
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                    "violation_type": "DEVICE_CLONE",
                    "cert_validities": (
                        sorted(list(certs_in_window))
                        if certs_in_window
                        else []
                    ),
                    "conflicting_hosts": sorted(list(unique_hosts)),
                    "flapping_count": len(history),
                    "host_switches": host_switches,
                    "reason": "Rapid IP hopping across distinct hosts with identical credentials",
                }
                return "DEVICE_CLONE", violation_details

    return None, None


def extract_device_sn(payload: dict, headers: dict) -> str | None:
    """Извлекает и валидирует Device SN из payload и headers AMQP-сообщения."""
    user = payload.get("user") or headers.get("user")
    if user and isinstance(user, str) and not is_ignored_or_service_identity(user):
        return user.strip()

    client_props = payload.get("client_properties") or headers.get("client_properties")
    if isinstance(client_props, dict):
        client_id = client_props.get("client_id")
        if (
            client_id
            and isinstance(client_id, str)
            and not is_ignored_or_service_identity(client_id)
        ):
            return client_id.strip()

    client_id_hdr = headers.get("client_id") or payload.get("client_id")
    if (
        client_id_hdr
        and isinstance(client_id_hdr, str)
        and not is_ignored_or_service_identity(client_id_hdr)
    ):
        return client_id_hdr.strip()

    return None


class DeviceService:
    @classmethod
    async def get_list(cls, session: AsyncSession, org_id, device_id: int | None):
        return await DeviceRepo.get(session, org_id, device_id)

    @classmethod
    async def get_connect_status_ids(cls, device_ids: [int]):
        pass

    @classmethod
    async def get_connect_status_sns(cls, sn_arr: [str]):
        pass

    @classmethod
    async def handle_connection_event(
        cls,
        session: AsyncSession,
        routing_key: str,
        payload: dict,
        headers: dict,
    ) -> bool:
        """Обрабатывает AMQP-событие connection.created или connection.closed."""
        device_sn = extract_device_sn(payload, headers)
        if not device_sn:
            log.debug(
                "Ignored non-device connection event (routing_key=%s): user=%s, client_id=%s",
                routing_key,
                payload.get("user") or headers.get("user"),
                headers.get("client_id"),
            )
            return False

        conn_name = payload.get("name") or headers.get("name")
        connected_at = payload.get("connected_at") or headers.get("connected_at")

        details = {
            "conn_name": conn_name,
            "name": conn_name,
            "peer_host": payload.get("peer_host") or headers.get("peer_host"),
            "peer_port": payload.get("peer_port") or headers.get("peer_port"),
            "ssl": payload.get("ssl") if "ssl" in payload else headers.get("ssl"),
            "ssl_cipher": payload.get("ssl_cipher") or headers.get("ssl_cipher"),
            "ssl_protocol": payload.get("ssl_protocol") or headers.get("ssl_protocol"),
            "peer_cert_subject": payload.get("peer_cert_subject") or headers.get("peer_cert_subject"),
            "peer_cert_validity": payload.get("peer_cert_validity") or headers.get("peer_cert_validity"),
            "protocol": payload.get("protocol") or headers.get("protocol"),
            "connected_at": connected_at,
            "bytes_received": payload.get("recv_oct") or headers.get("recv_oct"),
            "bytes_sent": payload.get("send_oct") or headers.get("send_oct"),
            "client_properties": payload.get("client_properties") or headers.get("client_properties"),
        }
        details = {k: v for k, v in details.items() if v is not None}

        if "connection.created" in routing_key:
            # Обновляем connection.details через RMQ Management API в момент подключения
            # (актуализирует данные сертификата mTLS, шифрования и сокета)
            try:
                single_details = await RmqAdminApi.get_single_connection_details(
                    conn_name=conn_name, sn=device_sn, timeout_sec=2.0
                )
                if single_details and isinstance(single_details, dict):
                    conn_name = single_details.get("name") or conn_name
                    connected_at = single_details.get("connected_at") or connected_at
                    details.update(
                        {
                            "conn_name": conn_name,
                            "name": conn_name,
                            "user": single_details.get("user") or details.get("user"),
                            "peer_host": single_details.get("peer_host") or details.get("peer_host"),
                            "peer_port": single_details.get("peer_port") or details.get("peer_port"),
                            "ssl": single_details.get("ssl") if "ssl" in single_details else details.get("ssl"),
                            "ssl_cipher": single_details.get("ssl_cipher") or details.get("ssl_cipher"),
                            "ssl_protocol": single_details.get("ssl_protocol") or details.get("ssl_protocol"),
                            "peer_cert_subject": single_details.get("peer_cert_subject") or details.get("peer_cert_subject"),
                            "peer_cert_validity": single_details.get("peer_cert_validity") or details.get("peer_cert_validity"),
                            "protocol": single_details.get("protocol") or details.get("protocol"),
                            "connected_at": connected_at,
                            "bytes_received": single_details.get("recv_oct") or details.get("bytes_received"),
                            "bytes_sent": single_details.get("send_oct") or details.get("bytes_sent"),
                            "recv_oct": single_details.get("recv_oct") or details.get("recv_oct"),
                            "send_oct": single_details.get("send_oct") or details.get("send_oct"),
                            "client_properties": single_details.get("client_properties") or details.get("client_properties"),
                        }
                    )
                    details = {k: v for k, v in details.items() if v is not None}
            except Exception as e:
                log.debug("Failed to fetch fresh connection details for %s: %s", device_sn, e)

            # Проверка на коллизии (SN_COLLISION / DEVICE_CLONE)
            violation_type, violation_details = evaluate_connection_collision(
                sn=device_sn,
                peer_host=details.get("peer_host"),
                peer_port=details.get("peer_port"),
                cert_validity=details.get("peer_cert_validity"),
                conn_name=conn_name,
            )

            if violation_type and violation_details:
                log.warning(
                    "Violation %s detected for device SN=%s: %s. Blocking device in RMQ and DB.",
                    violation_type,
                    device_sn,
                    violation_details,
                )
                await DeviceRepo.mark_device_blocked(
                    session=session,
                    sn=device_sn,
                    violation_type=violation_type,
                    violation_details=violation_details,
                    actor="system/detector",
                )
                await session.commit()
                # Автоматически блокируем в RabbitMQ и сбрасываем сокеты
                await RmqAdminApi.block_device_user(device_sn)
                return False

            res = await DeviceRepo.handle_connection_created(
                session=session,
                sn=device_sn,
                conn_name=conn_name,
                connected_at=connected_at,
                details=details,
            )
            await session.commit()
            if res is False:
                # Устройство уже заблокировано в БД -> сбрасываем сокет в RMQ
                await RmqAdminApi.block_device_user(device_sn)
                log.info("Handled connection.created for blocked %s (conn_name=%s)", device_sn, conn_name)
            else:
                log.info("Handled connection.created for %s (conn_name=%s)", device_sn, conn_name)
            return res
        elif "connection.closed" in routing_key:
            res = await DeviceRepo.handle_connection_closed(
                session=session,
                sn=device_sn,
                conn_name=conn_name,
                closed_at=connected_at,
                details=details,
            )
            await session.commit()
            log.info(
                "Handled connection.closed for %s (conn_name=%s, reset=%s)",
                device_sn,
                conn_name,
                res,
            )
            return res
        else:
            log.warning("Unknown connection event routing key: %s", routing_key)
            return False

    @classmethod
    async def reconcile_device_connections(
        cls,
        session: AsyncSession,
        time_budget: float | None = None,
        chunk_size: int | None = None,
    ) -> dict[str, int]:
        """Фоновая сверка (Reconciliation Loop) между RabbitMQ Management API и БД.

        Выполняет порционную обработку списка терминалов (chunks по 50-100 устройств)
        без блокировки event loop, с контролем временного бюджета.
        """
        budget = (
            time_budget
            if time_budget is not None
            else settings.rmq.device_sync_time_budget_sec
        )
        chunk_sz = (
            chunk_size
            if chunk_size is not None
            else settings.rmq.device_sync_chunk_size
        )
        start_time = time.monotonic()

        log.info(
            "Starting device connections reconciliation (time_budget=%.1fs, chunk_size=%d)...",
            budget,
            chunk_sz,
        )

        # 1. Fetch active connections from RMQ
        raw_conns = await RmqAdminApi.get_all_connections(
            time_budget_sec=min(budget / 2, 10.0), page_size=chunk_sz
        )

        active_map: dict[str, dict[str, Any]] = {}
        for conn in raw_conns:
            sn = extract_device_sn_from_conn(conn)
            if sn:
                active_map[sn] = conn

        # 2. Fetch all DB connections
        db_connections = await DeviceRepo.get_all_connections(session)
        if not db_connections:
            log.info("No device connections found in DB to reconcile.")
            return {
                "total_db": 0,
                "online_rmq": len(active_map),
                "reconciled_online": 0,
                "reconciled_offline": 0,
                "updated_telemetry": 0,
            }

        reconciled_online = 0
        reconciled_offline = 0
        updated_telemetry = 0

        # 3. Process in chunks
        for i in range(0, len(db_connections), chunk_sz):
            elapsed = time.monotonic() - start_time
            if elapsed >= budget:
                log.warning(
                    "Reconciliation loop time budget reached (%.2fs >= %.2fs). Processed %d/%d devices.",
                    elapsed,
                    budget,
                    i,
                    len(db_connections),
                )
                break

            chunk = db_connections[i : i + chunk_sz]
            for conn_row in chunk:
                sn = conn_row.client_id
                if not sn:
                    continue

                if conn_row.is_blocked:
                    if sn in active_map:
                        await RmqAdminApi.block_device_user(sn)
                        reconciled_offline += 1
                    continue

                if sn in active_map:
                    raw_conn = active_map[sn]
                    conn_name = raw_conn.get("name")
                    connected_at_raw = raw_conn.get("connected_at")
                    dt_conn = None
                    if isinstance(connected_at_raw, (int, float)):
                        if connected_at_raw > 1e11:
                            dt_conn = datetime.fromtimestamp(
                                connected_at_raw / 1000, tz=timezone.utc
                            ).replace(tzinfo=None)
                        else:
                            dt_conn = datetime.fromtimestamp(
                                connected_at_raw, tz=timezone.utc
                            ).replace(tzinfo=None)

                    telemetry = {
                        "conn_name": conn_name,
                        "name": conn_name,
                        "peer_host": raw_conn.get("peer_host"),
                        "peer_port": raw_conn.get("peer_port"),
                        "ssl": raw_conn.get("ssl"),
                        "ssl_cipher": raw_conn.get("ssl_cipher"),
                        "ssl_protocol": raw_conn.get("ssl_protocol"),
                        "peer_cert_subject": raw_conn.get("peer_cert_subject"),
                        "peer_cert_validity": raw_conn.get("peer_cert_validity"),
                        "client_properties": raw_conn.get("client_properties"),
                        "protocol": raw_conn.get("protocol"),
                        "connected_at": connected_at_raw,
                        "bytes_received": raw_conn.get("recv_oct"),
                        "bytes_sent": raw_conn.get("send_oct"),
                        "recv_oct": raw_conn.get("recv_oct"),
                        "send_oct": raw_conn.get("send_oct"),
                    }

                    if not conn_row.last_checked_result:
                        conn_row.last_checked_result = True
                        reconciled_online += 1

                    conn_row.checked_at = datetime.now(timezone.utc).replace(
                        tzinfo=None
                    )
                    if dt_conn:
                        conn_row.connected_at = dt_conn

                    current_details = (
                        dict(conn_row.details)
                        if isinstance(conn_row.details, dict)
                        else {}
                    )
                    current_details.update(
                        {k: v for k, v in telemetry.items() if v is not None}
                    )
                    conn_row.details = current_details
                    updated_telemetry += 1
                else:
                    if conn_row.last_checked_result:
                        conn_row.last_checked_result = False
                        conn_row.checked_at = datetime.now(timezone.utc).replace(
                            tzinfo=None
                        )
                        if conn_row.details and isinstance(conn_row.details, dict):
                            current_details = dict(conn_row.details)
                            current_details["conn_name"] = None
                            conn_row.details = current_details
                        reconciled_offline += 1

            await session.commit()
            await asyncio.sleep(0.01)

        log.info(
            "Device connections reconciliation finished in %.2fs: total_db=%d, online_rmq=%d, reconciled_online=%d, reconciled_offline=%d, updated_telemetry=%d",
            time.monotonic() - start_time,
            len(db_connections),
            len(active_map),
            reconciled_online,
            reconciled_offline,
            updated_telemetry,
        )

        return {
            "total_db": len(db_connections),
            "online_rmq": len(active_map),
            "reconciled_online": reconciled_online,
            "reconciled_offline": reconciled_offline,
            "updated_telemetry": updated_telemetry,
        }

    @classmethod
    async def update_device_connections(cls, session: AsyncSession):
        """Псевдоним для совместимости."""
        return await cls.reconcile_device_connections(session)

    @classmethod
    async def proxy_upsert_tag(
        cls, session, org_id, device_id, tag_value: DeviceTagPut
    ):
        if tag_value.tag.isascii():
            if len(tag_value.value) > 0:
                try:
                    tag_id = await DeviceRepo.upsert_tag(
                        session, org_id, device_id, tag_value.tag, tag_value.value
                    )
                except:
                    raise HTTPException(
                        status_code=404, detail="Tag/device_id uniqes error."
                    )
            else:
                raise HTTPException(status_code=404, detail="Value is empty")
        else:
            raise HTTPException(status_code=404, detail="Tag is not ascii")
        return tag_id

    @classmethod
    async def get_gauges(
        cls,
        session,
        org_id,
        device_id: int | None = None,
        type: str | None = None,
    ):
        """
        Получить gauges по устройствам в организации с пагинацией.
        """
        try:
            result = await DeviceRepo.get_gauges_page(
                session,
                org_id=org_id,
                device_id=device_id,
                type=type,
            )
            if result is None or len(result.items) == 0:
                raise HTTPException(status_code=404, detail="No gauges found")
            return result
        except Exception as e:
            log.error("Error fetching gauges: %s", e)
            raise HTTPException(status_code=500, detail="Internal server error")
