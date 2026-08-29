import json
from datetime import datetime, timezone

from fastapi_pagination.ext.sqlalchemy import apaginate

from core.logging_config import setup_module_logger
from typing import Any, List

from sqlalchemy import select, not_, func, update, text, sql
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import joinedload, load_only

from core.models import (
    Device,
    DeviceConnection,
    Org,
    DeviceTag,
    DeviceOrgBind,
    DeviceGauge,
)
from core.schemas.devices import DeviceConnectStatus

log = setup_module_logger(__name__, "repo_devices.log")


class DeviceRepo:

    @classmethod
    async def get(cls, session: AsyncSession, org_id: int, device_id: int | None):
        stmt_org = (
            select(DeviceOrgBind.device_id)
            .where(DeviceOrgBind.org_id == org_id)
            .subquery("devices")
        )
        if device_id is not None:
            stmt_org = (
                select(DeviceOrgBind.device_id)
                .where(
                    DeviceOrgBind.org_id == org_id, DeviceOrgBind.device_id == device_id
                )
                .subquery("devices")
            )

        stmt = (
            select(Device)
            .options(load_only(Device.device_id, Device.sn))
            .options(joinedload(Device.connection))
            .options(joinedload(Device.device_tags))
            .options(joinedload(Device.device_gauges))
            .where(Device.device_id.in_(select(stmt_org.c.device_id)))
            .where(Device.is_deleted == False)
        )

        result = await session.execute(stmt)
        return result.unique().scalars().all()

    @classmethod
    async def get_device_sn(
        cls, session: AsyncSession, device_id: int | None = 0, org_id: int | None = 0
    ) -> str | None:
        stmt = (
            select(Device.sn)
            .join(Device.org_bind)
            .where(
                Device.device_id == device_id,
                Device.is_deleted == False,
                DeviceOrgBind.org_id == org_id,
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @classmethod
    async def get_org_id_by_device_id(
        cls, session: AsyncSession, device_id: int
    ) -> int | None:
        result = await session.execute(
            select(DeviceOrgBind.org_id)
            .where(DeviceOrgBind.device_id == device_id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_device_id(
        cls, session: AsyncSession, sn: str | None = "", org_id: int | None = 0
    ) -> int | None:
        if not sn:
            return None

        stmt = select(Device.device_id).where(
            Device.sn == sn, Device.is_deleted == False
        )
        if org_id > 0:
            stmt = stmt.join(Device.org_bind).where(DeviceOrgBind.org_id == org_id)

        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @classmethod
    async def find_missing_devices(cls, session, sn_list) -> List[str]:
        """
        Возвращает список серийных номеров из `sn_list`, которых НЕТ в базе.
        На самом деле — логика противоположная названию.
        """
        # Исправлено: ищем те, что НЕ входят в переданный список
        lu_q = select(Device.sn).where(not_(Device.sn.in_(sn_list)))
        lu = await session.execute(lu_q)
        result = lu.scalars().all()
        log.debug("## device repo get not in list devices = %s", result)
        return result

    @classmethod
    async def add_devices(cls, session: AsyncSession, device_list: Any):
        # Подготовка данных
        device_values = [
            {"device_id": int(d["device_id"]), "sn": d["serial_number"]}
            for d in device_list
        ]
        org_values = [{"org_id": int(d["org_id"])} for d in device_list]
        bind_values = [
            {"device_id": int(d["device_id"]), "org_id": int(d["org_id"])}
            for d in device_list
        ]
        conn_values = [
            {"device_id": int(d["device_id"]), "client_id": d["serial_number"]}
            for d in device_list
        ]

        # Выполнение в одном порядке, без commit между
        await session.execute(
            insert(Device)
            .values(device_values)
            .on_conflict_do_update(
                index_elements=["device_id"], set_=dict(sn=insert(Device).excluded.sn)
            )
        )
        await session.execute(insert(Org).values(org_values).on_conflict_do_nothing())
        await session.execute(
            insert(DeviceOrgBind)
            .values(bind_values)
            .on_conflict_do_update(
                index_elements=["device_id"],
                set_=dict(org_id=insert(DeviceOrgBind).excluded.org_id),
            )
        )
        await session.execute(
            insert(DeviceConnection)
            .values(conn_values)
            .on_conflict_do_update(
                index_elements=["device_id"],
                set_=dict(client_id=insert(DeviceConnection).excluded.client_id),
            )
        )

        await session.commit()

    @classmethod
    async def update_connections(
        cls, session: AsyncSession, device_conn: list[DeviceConnectStatus]
    ):
        """
        Пакетное обновление статуса соединений по client_id.
        Использует временную таблицу через JSON и функцию json_to_recordset.
        Время checked_at вычисляется прямо в SQL через now().
        """
        if not device_conn:
            return

        # Подготавливаем данные в виде списка словарей
        data = [
            {
                "client_id": dc.client_id,
                "details": dc.details.model_dump(mode="json"),
                "connected_at": (dc.connected_at / 1000) if dc.connected_at else None,
            }
            for dc in device_conn
        ]

        # Преобразуем в JSON-строку
        json_data = json.dumps(data)

        # Убираем передачу checked_at как параметра — используем now() в SQL
        stmt = text("""
                UPDATE tb_device_connections AS conn
                SET 
                    checked_at = NOW(),
                    last_checked_result = TRUE,
                    details = data.details::jsonb,
                    connected_at = CASE 
                        WHEN data.connected_at IS NOT NULL THEN to_timestamp(data.connected_at)
                        ELSE NULL 
                    END
                FROM json_to_recordset(:json_data) AS data(
                    client_id text,
                    details jsonb,
                    connected_at double precision
                )
                WHERE conn.client_id = data.client_id
            """)

        await session.execute(
            stmt,
            {
                "json_data": json_data,
            },
        )
        # commit in service layer after all updates
        # await session.commit()
        log.info("Updated %d connections", len(device_conn))

    @classmethod
    async def reset_connection_flag(cls, session: AsyncSession, sn_arr: list[str]):
        """
        Сбрасывает флаг последней проверки для списка serial numbers.
        """
        if not sn_arr:
            return
        await session.execute(
            update(DeviceConnection)
            .values(last_checked_result=False)
            .where(DeviceConnection.client_id.in_(sn_arr))
        )
        # commit in service with transaction (reset-update)
        # await session.commit()

    @classmethod
    async def update_connect_flag(
        cls, session: AsyncSession, sn: str, flag_name: str, value: bool
    ):
        """
        Атомарно обновляет флаг подключения (app_connect или svc_connect)
        и обновляет checked_at = NOW().
        Не перезаписывает и не сбрасывает last_checked_result.
        Если запись в таблице DeviceConnection отсутствует, создает/актуализирует её.
        """
        if flag_name not in ("app_connect", "svc_connect"):
            raise ValueError(f"Invalid connection flag name: {flag_name}")

        stmt = (
            update(DeviceConnection)
            .where(DeviceConnection.client_id == sn)
            .values(
                {
                    flag_name: value,
                    "checked_at": func.now(),
                }
            )
        )
        res = await session.execute(stmt)
        if res.rowcount == 0:
            dev_id = await cls.get_device_id(session, sn=sn)
            if dev_id is not None:
                stmt_by_dev = select(DeviceConnection).where(
                    DeviceConnection.device_id == dev_id
                )
                res_dev = await session.execute(stmt_by_dev)
                conn_row = res_dev.scalar_one_or_none()
                now_dt = datetime.now(timezone.utc).replace(tzinfo=None)
                if conn_row is not None:
                    conn_row.client_id = sn
                    setattr(conn_row, flag_name, value)
                    conn_row.checked_at = now_dt
                else:
                    new_conn = DeviceConnection(
                        device_id=dev_id,
                        client_id=sn,
                        last_checked_result=False,
                        checked_at=now_dt,
                        **{flag_name: value},
                    )
                    session.add(new_conn)

    @classmethod
    async def handle_connection_created(
        cls,
        session: AsyncSession,
        sn: str,
        conn_name: str | None = None,
        connected_at: datetime | int | float | None = None,
        details: dict | None = None,
    ) -> bool:
        """
        Обрабатывает событие connection.created для устройства по SN.
        Устанавливает last_checked_result = True, обновляет checked_at,
        connected_at и сохраняет conn_name и телеметрию в details.
        Не сбрасывает и не изменяет app_connect и svc_connect.
        """
        dt_connected_at = None
        if isinstance(connected_at, (int, float)):
            if connected_at > 1e11:
                dt_connected_at = datetime.fromtimestamp(
                    connected_at / 1000, tz=timezone.utc
                ).replace(tzinfo=None)
            else:
                dt_connected_at = datetime.fromtimestamp(
                    connected_at, tz=timezone.utc
                ).replace(tzinfo=None)
        elif isinstance(connected_at, datetime):
            dt_connected_at = (
                connected_at.replace(tzinfo=None)
                if connected_at.tzinfo
                else connected_at
            )

        details_dict = dict(details) if isinstance(details, dict) else {}
        if conn_name:
            details_dict["conn_name"] = conn_name
            details_dict["name"] = conn_name
        if connected_at is not None:
            details_dict["connected_at"] = connected_at

        stmt = select(DeviceConnection).where(DeviceConnection.client_id == sn)
        res = await session.execute(stmt)
        conn_row = res.scalar_one_or_none()

        dev_id = None
        if conn_row is None:
            dev_id = await cls.get_device_id(session, sn=sn)
            if dev_id is not None:
                stmt_dev = select(DeviceConnection).where(
                    DeviceConnection.device_id == dev_id
                )
                res_dev = await session.execute(stmt_dev)
                conn_row = res_dev.scalar_one_or_none()

        now_dt = datetime.now(timezone.utc).replace(tzinfo=None)

        if conn_row is not None:
            conn_row.client_id = sn
            conn_row.last_checked_result = True
            conn_row.checked_at = now_dt
            if dt_connected_at is not None:
                conn_row.connected_at = dt_connected_at
            elif conn_row.connected_at is None:
                conn_row.connected_at = now_dt

            merged_details = (
                dict(conn_row.details)
                if isinstance(conn_row.details, dict)
                else {}
            )
            merged_details.update(details_dict)
            conn_row.details = merged_details
            return True
        else:
            if dev_id is None:
                dev_id = await cls.get_device_id(session, sn=sn)
            if dev_id is not None:
                new_conn = DeviceConnection(
                    device_id=dev_id,
                    client_id=sn,
                    last_checked_result=True,
                    checked_at=now_dt,
                    connected_at=dt_connected_at or now_dt,
                    details=details_dict,
                )
                session.add(new_conn)
                return True
            else:
                log.info("Received connection.created for unknown device SN=%s", sn)
                return False

    @classmethod
    async def handle_connection_closed(
        cls,
        session: AsyncSession,
        sn: str,
        conn_name: str | None = None,
        closed_at: datetime | int | float | None = None,
        details: dict | None = None,
    ) -> bool:
        """
        Обрабатывает событие connection.closed для устройства по SN.
        Защита от race condition: сбрасывает last_checked_result = False только если
        закрывающееся соединение совпадает с текущим активным conn_name или если
        активное имя соединения не зафиксировано.
        Не сбрасывает и не изменяет app_connect и svc_connect.
        """
        stmt = select(DeviceConnection).where(DeviceConnection.client_id == sn)
        res = await session.execute(stmt)
        conn_row = res.scalar_one_or_none()

        if conn_row is None:
            dev_id = await cls.get_device_id(session, sn=sn)
            if dev_id is not None:
                stmt_dev = select(DeviceConnection).where(
                    DeviceConnection.device_id == dev_id
                )
                res_dev = await session.execute(stmt_dev)
                conn_row = res_dev.scalar_one_or_none()

        if conn_row is None:
            return False

        now_dt = datetime.now(timezone.utc).replace(tzinfo=None)

        if conn_row.last_checked_result:
            current_details = (
                conn_row.details if isinstance(conn_row.details, dict) else {}
            )
            current_conn_name = (
                current_details.get("conn_name") or current_details.get("name")
            )

            # Если имена обоих сокетов известны и не совпадают -> закрылся старый сокет (гонка при реконнекте)
            if conn_name and current_conn_name and conn_name != current_conn_name:
                log.info(
                    "Race condition on connection.closed for SN=%s: closed conn '%s' != active conn '%s'. Skipping status reset.",
                    sn,
                    conn_name,
                    current_conn_name,
                )
                return False

            conn_row.last_checked_result = False
            conn_row.checked_at = now_dt
            merged_details = dict(current_details)
            merged_details["conn_name"] = None
            conn_row.details = merged_details
            return True
        else:
            conn_row.checked_at = now_dt
            return True

    @classmethod
    async def get_all_connections(cls, session: AsyncSession) -> list[DeviceConnection]:
        """Возвращает все записи DeviceConnection из БД."""
        stmt = select(DeviceConnection)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @classmethod
    async def get_devices_with_known_connect_state(
        cls, session: AsyncSession
    ) -> set[str]:
        """
        Возвращает множество client_id (serial numbers) устройств,
        у которых хотя бы один из LWT флагов (app_connect или svc_connect) не NULL.
        """
        stmt = select(DeviceConnection.client_id).where(
            DeviceConnection.app_connect.isnot(None)
            | DeviceConnection.svc_connect.isnot(None)
        )
        result = await session.execute(stmt)
        return {sn for sn in result.scalars().all() if sn}

    @classmethod
    async def list(cls, session: AsyncSession) -> List[str]:
        """
        Возвращает все client_id (serial numbers) из таблицы подключений.
        """
        stmt = select(DeviceConnection.client_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())
        # log.debug("#### device repo list device as scalar select: %s", sn_list)

    @classmethod
    async def upsert_tag(
        cls, session: AsyncSession, org_id: int, device_id: int, tag: str, value: str
    ) -> int:
        stmt = (
            insert(DeviceTag)
            .values(device_id=device_id, tag=tag, value=value)
            .on_conflict_do_update(
                constraint="uq_tb_device_tags_device_id_tag_is_deleted",
                set_=dict(value=value),
            )
            .returning(DeviceTag.id)
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.scalar_one()

    @classmethod
    async def upsert_gauge(
        cls, session: AsyncSession, org_id: int, device_id: int, type: str, gauges: dict
    ) -> int:
        stmt = (
            insert(DeviceGauge)
            .values(device_id=device_id, type=type, gauges=gauges)
            .on_conflict_do_update(
                constraint="uq_tb_device_gauges_device_id_type_is_deleted",
                set_=dict(gauges=gauges, updated_at=func.now()),
            )
            .returning(DeviceGauge.id)
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.scalar_one()

    @classmethod
    async def get_gauges_page(
        cls,
        session: AsyncSession,
        org_id: int,
        device_id: int | None = None,
        type: str | None = None,
    ):
        """
        Возвращает страницу с гаузами устройств в организации.
        Поддерживает фильтрацию по device_id и type.
        """
        stmt = (
            select(DeviceGauge)
            .join(Device)
            .join(Device.org_bind)
            .where(Device.is_deleted == False)
            .where(DeviceOrgBind.org_id == org_id)
            .where(DeviceGauge.is_deleted == False)
        )

        if device_id is not None:
            stmt = stmt.where(Device.device_id == device_id)

        if type is not None:
            stmt = stmt.where(DeviceGauge.type == type)

        return await apaginate(session, stmt)

    @classmethod
    async def provision_terminals(
        cls,
        session: AsyncSession,
        terminals_data: list[dict[str, Any]],
    ) -> None:
        """Upsert Org, Device, DeviceOrgBind, and DeviceConnection for provisioned terminals."""
        if not terminals_data:
            return

        device_values = [
            {
                "device_id": int(d["device_id"]),
                "sn": str(d["sn"]),
                "is_deleted": False,
                "deleted_at": None,
            }
            for d in terminals_data
        ]
        org_values = [
            {"org_id": int(d["org_id"]), "name": d.get("name") or f"Org {d['org_id']}"}
            for d in terminals_data
        ]
        bind_values = [
            {"device_id": int(d["device_id"]), "org_id": int(d["org_id"])}
            for d in terminals_data
        ]
        conn_values = [
            {"device_id": int(d["device_id"]), "client_id": str(d["sn"])}
            for d in terminals_data
        ]

        # 1. Upsert Orgs
        await session.execute(
            insert(Org)
            .values(org_values)
            .on_conflict_do_nothing(index_elements=["org_id"])
        )

        # 2. Upsert Devices
        await session.execute(
            insert(Device)
            .values(device_values)
            .on_conflict_do_update(
                index_elements=["device_id"],
                set_=dict(
                    sn=insert(Device).excluded.sn,
                    is_deleted=False,
                    deleted_at=None,
                ),
            )
        )

        # 3. Upsert DeviceOrgBind
        await session.execute(
            insert(DeviceOrgBind)
            .values(bind_values)
            .on_conflict_do_update(
                index_elements=["device_id"],
                set_=dict(org_id=insert(DeviceOrgBind).excluded.org_id),
            )
        )

        # 4. Upsert DeviceConnection
        await session.execute(
            insert(DeviceConnection)
            .values(conn_values)
            .on_conflict_do_update(
                index_elements=["device_id"],
                set_=dict(client_id=insert(DeviceConnection).excluded.client_id),
            )
        )

        # 5. Optional tags
        for d in terminals_data:
            tags = d.get("tags")
            if tags and isinstance(tags, dict):
                for tag_k, tag_v in tags.items():
                    if tag_k and tag_v:
                        await session.execute(
                            insert(DeviceTag)
                            .values(
                                device_id=int(d["device_id"]),
                                tag=str(tag_k),
                                value=str(tag_v),
                                is_system_tag=True,
                            )
                            .on_conflict_do_update(
                                index_elements=["device_id", "tag", "is_deleted"],
                                set_=dict(value=str(tag_v)),
                            )
                        )

        await session.commit()

    @classmethod
    async def get_terminals_status_by_device_ids(
        cls,
        session: AsyncSession,
        device_ids: list[int],
    ) -> list[dict[str, Any]]:
        """Get provisioning and connection status for a list of device_ids."""
        if not device_ids:
            return []

        stmt = (
            select(
                Device.device_id,
                Device.sn,
                DeviceOrgBind.org_id,
                DeviceConnection.client_id,
                DeviceConnection.last_checked_result,
                DeviceConnection.connected_at,
                DeviceConnection.checked_at,
            )
            .outerjoin(DeviceOrgBind, DeviceOrgBind.device_id == Device.device_id)
            .outerjoin(DeviceConnection, DeviceConnection.device_id == Device.device_id)
            .where(Device.device_id.in_(device_ids), Device.is_deleted == False)
        )
        res = await session.execute(stmt)
        rows = res.fetchall()

        found_map: dict[int, dict[str, Any]] = {}
        for row in rows:
            dev_id, sn, org_id, _client_id, is_conn, conn_at, chk_at = row
            found_map[dev_id] = {
                "device_id": dev_id,
                "sn": sn,
                "org_id": org_id,
                "is_provisioned": True,
                "is_online": bool(is_conn),
                "connected_at": conn_at,
                "checked_at": chk_at,
            }

        result = []
        for d_id in device_ids:
            if d_id in found_map:
                result.append(found_map[d_id])
            else:
                result.append(
                    {
                        "device_id": d_id,
                        "sn": None,
                        "org_id": None,
                        "is_provisioned": False,
                        "is_online": False,
                        "connected_at": None,
                        "checked_at": None,
                    }
                )
        return result
