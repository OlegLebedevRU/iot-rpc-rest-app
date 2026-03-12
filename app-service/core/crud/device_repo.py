from core.logging_config import setup_module_logger
from typing import Any, List

from sqlalchemy import select, not_, func, update, text
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
            (
                select(DeviceOrgBind.device_id)
                .where(DeviceOrgBind.org_id == org_id)
                .subquery("devices")
            )
            if device_id is None
            else (
                select(DeviceOrgBind.device_id).where(
                    DeviceOrgBind.org_id == org_id, DeviceOrgBind.device_id == device_id
                )
            ).subquery("devices")
        )

        stmt_44 = (
            select(
                DeviceGauge.device_id,
                (DeviceGauge.gauges["300"][0]["338"]).label("active_ws"),
                (func.now() - DeviceGauge.updated_at).label("interval_sec"),
            )
        ).subquery("gauge_44_338")

        stmt = (
            select(Device)
            .options(load_only(Device.device_id, Device.sn))
            .options(joinedload(Device.connection))
            .options(joinedload(Device.device_tags))
            .options(joinedload(Device.device_gauges))
            .where(Device.device_id.in_(select(stmt_org.c.device_id)))
            .where(Device.is_deleted == False)
        )

        devs = await session.execute(stmt)
        return devs.unique().scalars().all()

    @classmethod
    async def get_device_sn(
        cls, session: AsyncSession, device_id: int | None = 0, org_id: int | None = 0
    ) -> str | None:
        stmt = (
            select(Device.sn)
            .join(Device.org_bind)
            .where(Device.device_id == device_id)
            .where(Device.is_deleted == False)
            .where(DeviceOrgBind.org_id == org_id)
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
        ins_device = insert(Device)
        insert_stmt = (
            insert(Device)
            .values(
                [
                    {"device_id": int(d["device_id"]), "sn": d["serial_number"]}
                    for d in device_list
                ]
            )
            .on_conflict_do_update(
                index_elements=["device_id"],
                set_=dict(sn=ins_device.excluded.sn),
            )
        )

        insert_stmt1 = (
            insert(Org)
            .values([{"org_id": int(d["org_id"])} for d in device_list])
            .on_conflict_do_nothing()
        )

        ins_bind = insert(DeviceOrgBind)
        insert_stmt2 = (
            insert(DeviceOrgBind)
            .values(
                [
                    {"device_id": int(d["device_id"]), "org_id": int(d["org_id"])}
                    for d in device_list
                ]
            )
            .on_conflict_do_update(
                index_elements=["device_id"],
                set_=dict(org_id=ins_bind.excluded.org_id),
            )
        )

        ins_conn = insert(DeviceConnection)
        insert_dev_conn = (
            insert(DeviceConnection)
            .values(
                [
                    {"device_id": int(d["device_id"]), "client_id": d["serial_number"]}
                    for d in device_list
                ]
            )
            .on_conflict_do_update(
                index_elements=["device_id"],
                set_=dict(client_id=ins_conn.excluded.client_id),
            )
        )

        await session.execute(insert_stmt)
        await session.execute(insert_stmt1)
        await session.execute(insert_stmt2)
        await session.execute(insert_dev_conn)
        await session.commit()

    @classmethod
    async def update_connections(
        cls, session: AsyncSession, device_conn: list[DeviceConnectStatus]
    ):
        """
        Пакетное обновление статуса соединений по client_id.
        Использует UNNEST для массивов в PostgreSQL.
        Общее время checked_at берётся один раз на всю операцию.
        """
        if not device_conn:
            return

        # Подготавливаем данные
        client_ids = [dc.client_id for dc in device_conn]
        details_list = [dc.details.model_dump(mode="json") for dc in device_conn]
        connected_at_timestamps = [
            (dc.connected_at / 1000) if dc.connected_at else None for dc in device_conn
        ]

        # Единый timestamp для всей операции
        checked_at = func.current_timestamp()

        stmt = text(f"""
            UPDATE {DeviceConnection.__tablename__}
            SET 
                checked_at = :checked_at,
                last_checked_result = TRUE,
                details = u.details::jsonb,
                connected_at = CASE 
                    WHEN u.connected_at IS NOT NULL THEN to_timestamp(u.connected_at)
                    ELSE NULL 
                END
            FROM (
                SELECT 
                    UNNEST(:client_ids::text[]) AS client_id,
                    UNNEST(:details_list::jsonb[]) AS details,
                    UNNEST(:connected_at_list) AS connected_at
            ) AS u
            WHERE {DeviceConnection.__tablename__}.client_id = u.client_id
        """)

        await session.execute(
            stmt,
            {
                "checked_at": checked_at,
                "client_ids": client_ids,
                "details_list": details_list,
                "connected_at_list": connected_at_timestamps,
            },
        )
        await session.commit()

    @classmethod
    async def reset_connection_flag(cls, session: AsyncSession, sn_arr: list[str]):
        """
        Сбрасывает флаг последней проверки для списка serial numbers.
        """
        await session.execute(
            update(DeviceConnection)
            .values(last_checked_result=False)
            .where(DeviceConnection.client_id.in_(sn_arr))
        )
        await session.commit()

    @classmethod
    async def list(cls, session: AsyncSession) -> List[str]:
        """
        Возвращает все client_id (serial numbers) из таблицы подключений.
        """
        stmt = select(DeviceConnection.client_id)
        result = await session.execute(stmt)
        sn_list = result.scalars().all()
        log.debug("#### device repo list device as scalar select: %s", sn_list)
        return list(sn_list)

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
        return result.unique().scalars().one()

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
        return result.unique().scalars().one()
