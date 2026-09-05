import json
from datetime import datetime, timezone

from fastapi_pagination.ext.sqlalchemy import apaginate

from core.logging_config import setup_module_logger
from typing import Any, List

from sqlalchemy import select, not_, func, update, text, sql, case, cast, String, or_, and_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import joinedload, load_only, selectinload, contains_eager
from fastapi import HTTPException

from core.models import (
    Device,
    DeviceConnection,
    DeviceAuditLog,
    Org,
    DeviceTag,
    DeviceOrgBind,
    DeviceGauge,
)
from core.schemas.devices import (
    DeviceConnectStatus,
    DeviceListResponse,
    DeviceStats,
    DeviceListResult,
)

log = setup_module_logger(__name__, "repo_devices.log")


class DeviceRepo:

    @classmethod
    async def get(
        cls,
        session: AsyncSession,
        org_id: int,
        device_id: int | None = None,
        page: int = 1,
        size: int = 20,
        q: str | None = None,
        status: str | None = None,
        sort_by: str = "device_id",
        sort_order: str = "asc",
    ) -> DeviceListResponse:
        if page < 1:
            raise HTTPException(status_code=400, detail="page must be >= 1")
        if size < 1 or size > 100:
            raise HTTPException(status_code=400, detail="size must be between 1 and 100")

        sb = (sort_by or "device_id").strip().lower()
        if sb not in ("device_id", "sn", "connected_at", "status"):
            raise HTTPException(status_code=400, detail=f"Invalid sort_by: {sort_by}")

        so = (sort_order or "asc").strip().lower()
        if so not in ("asc", "desc"):
            raise HTTPException(status_code=400, detail=f"Invalid sort_order: {sort_order}")

        st = (status or "").strip().lower()
        if st and st not in ("all", "online", "offline", "blocked"):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: {status}. Allowed values: 'all', 'online', 'offline', 'blocked'",
            )

        online_cond = and_(
            DeviceConnection.last_checked_result.is_(True),
            or_(
                DeviceConnection.is_blocked.is_(False),
                DeviceConnection.is_blocked.is_(None),
            ),
        )
        offline_cond = and_(
            or_(
                DeviceConnection.last_checked_result.is_(False),
                DeviceConnection.last_checked_result.is_(None),
            ),
            or_(
                DeviceConnection.is_blocked.is_(False),
                DeviceConnection.is_blocked.is_(None),
            ),
        )
        blocked_cond = DeviceConnection.is_blocked.is_(True)

        stats_stmt = (
            select(
                func.count(Device.id).label("total"),
                func.count(case((online_cond, 1), else_=None)).label("online"),
                func.count(case((offline_cond, 1), else_=None)).label("offline"),
                func.count(case((blocked_cond, 1), else_=None)).label("blocked"),
            )
            .select_from(Device)
            .join(DeviceOrgBind, Device.device_id == DeviceOrgBind.device_id)
            .outerjoin(DeviceConnection, Device.device_id == DeviceConnection.device_id)
            .where(
                DeviceOrgBind.org_id == org_id,
                Device.is_deleted.is_(False),
            )
        )
        stats_res = await session.execute(stats_stmt)
        stats_row = stats_res.one()
        stats_data = DeviceStats(
            total=stats_row.total or 0,
            online=stats_row.online or 0,
            offline=stats_row.offline or 0,
            blocked=stats_row.blocked or 0,
        )

        where_clauses = [
            DeviceOrgBind.org_id == org_id,
            Device.is_deleted.is_(False),
        ]

        if device_id is not None:
            where_clauses.append(Device.device_id == device_id)

        has_status_filter = False
        if st == "online":
            where_clauses.append(online_cond)
            has_status_filter = True
        elif st == "offline":
            where_clauses.append(offline_cond)
            has_status_filter = True
        elif st == "blocked":
            where_clauses.append(blocked_cond)
            has_status_filter = True

        has_q_filter = False
        if q and q.strip():
            has_q_filter = True
            search_str = q.strip()
            pattern = f"%{search_str}%"
            tag_subq = (
                select(DeviceTag.device_id)
                .where(
                    DeviceTag.is_deleted.is_(False),
                    DeviceTag.tag.in_(["name", "description", "app", "sys"]),
                    DeviceTag.value.ilike(pattern),
                )
            )
            q_filter = or_(
                Device.sn.ilike(pattern),
                cast(Device.device_id, String).ilike(pattern),
                DeviceConnection.violation_type.ilike(pattern),
                Device.device_id.in_(tag_subq),
            )
            where_clauses.append(q_filter)

        if device_id is None and not has_status_filter and not has_q_filter:
            filtered_total = stats_data.total
        else:
            count_stmt = (
                select(func.count(Device.id))
                .select_from(Device)
                .join(DeviceOrgBind, Device.device_id == DeviceOrgBind.device_id)
                .outerjoin(DeviceConnection, Device.device_id == DeviceConnection.device_id)
                .where(*where_clauses)
            )
            filtered_total = (await session.scalar(count_stmt)) or 0

        pages = (filtered_total + size - 1) // size if filtered_total > 0 else 0

        order_by_list = []
        if sb == "device_id":
            order_by_list.append(Device.device_id.desc() if so == "desc" else Device.device_id.asc())
        elif sb == "sn":
            order_by_list.append(Device.sn.desc() if so == "desc" else Device.sn.asc())
            order_by_list.append(Device.device_id.desc() if so == "desc" else Device.device_id.asc())
        elif sb == "connected_at":
            conn_order = (
                DeviceConnection.connected_at.desc().nulls_last()
                if so == "desc"
                else DeviceConnection.connected_at.asc().nulls_last()
            )
            order_by_list.append(conn_order)
            order_by_list.append(Device.device_id.desc() if so == "desc" else Device.device_id.asc())
        elif sb == "status":
            status_order_expr = case(
                (DeviceConnection.is_blocked.is_(True), "blocked"),
                (DeviceConnection.last_checked_result.is_(True), "online"),
                else_="offline",
            )
            status_order = (
                status_order_expr.desc()
                if so == "desc"
                else status_order_expr.asc()
            )
            order_by_list.append(status_order)
            order_by_list.append(Device.device_id.desc() if so == "desc" else Device.device_id.asc())

        offset = (page - 1) * size
        stmt = (
            select(Device)
            .join(DeviceOrgBind, Device.device_id == DeviceOrgBind.device_id)
            .outerjoin(DeviceConnection, Device.device_id == DeviceConnection.device_id)
            .where(*where_clauses)
            .order_by(*order_by_list)
            .offset(offset)
            .limit(size)
            .options(
                contains_eager(Device.connection),
                selectinload(Device.device_tags),
                selectinload(Device.device_gauges),
            )
        )

        result = await session.execute(stmt)
        devices = list(result.unique().scalars().all())

        # Если запрошен конкретный терминал, обогащаем объект connection топ-5 событиями аудит-лога
        if device_id is not None and devices:
            for dev in devices:
                if dev.connection:
                    audit_logs = await cls.get_recent_audit_logs(
                        session, dev.device_id, limit=5
                    )
                    dev.connection.recent_audit_events = audit_logs

        return DeviceListResponse(
            items=devices,
            total=filtered_total,
            page=page,
            size=size,
            pages=pages,
            stats=stats_data,
        )

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
            if conn_row.is_blocked:
                log.info(
                    "Device SN=%s is BLOCKED (%s). Refusing connection.created status update.",
                    sn,
                    conn_row.violation_type,
                )
                return False

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
                set_=dict(
                    client_id=insert(DeviceConnection).excluded.client_id,
                    is_blocked=False,
                    violation_type=None,
                    violation_details=None,
                ),
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

        # 6. Audit log for provisioned terminals
        for d in terminals_data:
            dev_id = int(d["device_id"])
            org_id = int(d["org_id"])
            actor = d.get("actor") or "api/provisioning"
            await cls.add_audit_log(
                session=session,
                device_id=dev_id,
                org_id=org_id,
                event_type="PROVISIONED",
                actor=actor,
                details={"sn": str(d["sn"]), "name": d.get("name")},
            )

        await session.commit()

    @classmethod
    async def add_audit_log(
        cls,
        session: AsyncSession,
        device_id: int,
        org_id: int,
        event_type: str,
        actor: str | None = None,
        details: dict | None = None,
    ) -> DeviceAuditLog:
        """Создает запись в tb_device_audit_logs."""
        audit_entry = DeviceAuditLog(
            device_id=device_id,
            org_id=org_id,
            event_type=event_type,
            actor=actor,
            details=details,
        )
        session.add(audit_entry)
        return audit_entry

    @classmethod
    async def get_recent_audit_logs(
        cls,
        session: AsyncSession,
        device_id: int,
        limit: int = 5,
    ) -> list[DeviceAuditLog]:
        """Возвращает последние N записей аудит-лога для устройства."""
        stmt = (
            select(DeviceAuditLog)
            .where(DeviceAuditLog.device_id == device_id)
            .order_by(DeviceAuditLog.created_at.desc(), DeviceAuditLog.id.desc())
            .limit(limit)
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())

    @classmethod
    async def mark_device_blocked(
        cls,
        session: AsyncSession,
        sn: str,
        violation_type: str,
        violation_details: dict | None = None,
        actor: str = "system/detector",
    ) -> tuple[int | None, int | None]:
        """Помечает устройство как заблокированное при обнаружении коллизии (DEVICE_CLONE или SN_COLLISION),

        сохраняет детали нарушения и записывает событие в tb_device_audit_logs (идемпотентно).
        Возвращает (device_id, org_id).
        """
        stmt = select(DeviceConnection).where(DeviceConnection.client_id == sn)
        res = await session.execute(stmt)
        conn_row = res.scalar_one_or_none()

        dev_id = None
        if conn_row:
            dev_id = conn_row.device_id
        else:
            dev_id = await cls.get_device_id(session, sn=sn)
            if dev_id is not None:
                stmt_dev = select(DeviceConnection).where(
                    DeviceConnection.device_id == dev_id
                )
                res_dev = await session.execute(stmt_dev)
                conn_row = res_dev.scalar_one_or_none()

        if dev_id is None:
            log.warning("Cannot block unknown device SN=%s", sn)
            return None, None

        org_id = await cls.get_org_id_by_device_id(session, dev_id) or 0
        now_dt = datetime.now(timezone.utc).replace(tzinfo=None)

        was_blocked = conn_row.is_blocked if conn_row else False
        prev_violation = conn_row.violation_type if conn_row else None

        if conn_row:
            conn_row.is_blocked = True
            conn_row.last_checked_result = False
            conn_row.violation_type = violation_type
            conn_row.violation_details = violation_details
            conn_row.checked_at = now_dt
        else:
            conn_row = DeviceConnection(
                device_id=dev_id,
                client_id=sn,
                last_checked_result=False,
                checked_at=now_dt,
                is_blocked=True,
                violation_type=violation_type,
                violation_details=violation_details,
            )
            session.add(conn_row)

        # Пишем в аудит-лог только если статус блокировки изменился или сменился тип нарушения
        if not was_blocked or prev_violation != violation_type:
            await cls.add_audit_log(
                session=session,
                device_id=dev_id,
                org_id=org_id,
                event_type=violation_type,
                actor=actor,
                details=violation_details,
            )

        return dev_id, org_id

    @classmethod
    async def unblock_device(
        cls,
        session: AsyncSession,
        device_id: int,
        actor: str = "api/provisioning",
    ) -> None:
        """Сбрасывает флаги блокировки и нарушений в DeviceConnection."""
        stmt = select(DeviceConnection).where(DeviceConnection.device_id == device_id)
        res = await session.execute(stmt)
        conn_row = res.scalar_one_or_none()
        if conn_row and conn_row.is_blocked:
            conn_row.is_blocked = False
            conn_row.violation_type = None
            conn_row.violation_details = None
            org_id = await cls.get_org_id_by_device_id(session, device_id) or 0
            await cls.add_audit_log(
                session=session,
                device_id=device_id,
                org_id=org_id,
                event_type="UNBLOCKED",
                actor=actor,
                details={"reason": "Manual or provisioning unblock"},
            )

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
