import logging
from typing import Any
from sqlalchemy import select, not_, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy import update, exists
from sqlalchemy.orm import joinedload, with_expression

from core import settings
from core.models import Device, DeviceConnection, Org, DeviceTag
from core.models.devices import DeviceOrgBind, DeviceGauge
from core.schemas.devices import DeviceConnectStatus


log = logging.getLogger(__name__)
fh = logging.FileHandler("/var/log/app/repo_devices.log")
fh.setLevel(logging.INFO)
formatter = logging.Formatter(settings.logging.log_format)
fh.setFormatter(formatter)


class DeviceRepo:
    @classmethod
    async def get(cls, session: AsyncSession, org_id: int, device_id: int | None):
        stmt_org = (
            (
                select(DeviceOrgBind.device_id)
                .where(DeviceOrgBind.org_id == org_id)
                .subquery("devices")
                # .options(joinedload(DeviceOrgBind.org))
                # .where(DeviceOrgBind.org. == False)
            )
            if device_id is None
            else (
                select(DeviceOrgBind.device_id).where(
                    DeviceOrgBind.org_id == org_id, DeviceOrgBind.device_id == device_id
                )
                # .options(joinedload(DeviceOrgBind.org))
                # .where(Device.device_id == device_id)
            ).subquery("devices")
        )
        # test = await session.execute(select(stmt_org))
        # print(test.all())
        stmt = (
            select(Device)
            .options(joinedload(Device.connection))
            .options(joinedload(Device.device_tags))
            .options(joinedload(Device.device_gauges))
            .where(
                Device.device_id.in_(select(stmt_org.c.device_id))
            )  # stmt_org.c.device_id)
            # .where(Device.device_id.in_(device_ids))
            # .join(stmt_org, stmt_org.c.device_id==Device.device_id)
            # .where(Org.org_id == org_id)
        )
        devs = await session.execute(stmt)
        # devices = devs.all()
        devices = devs.unique().scalars().all()
        return devices

    @classmethod
    async def get_device_sn(
        cls, session: AsyncSession, device_id: int | None = 0, org_id: int | None = 0
    ) -> str | None:
        data = await session.execute(
            select(Device)
            .where(Device.device_id == device_id)
            .where(Device.is_deleted == False)
            .where(DeviceOrgBind.org_id == org_id)
        )
        r = data.unique().mappings().one_or_none()
        if r is not None:
            resp = r.Device.sn
        else:
            resp = None
        return resp

    @classmethod
    async def get_device_id(
        cls, session: AsyncSession, sn: str | None = "", org_id: int | None = 0
    ) -> int | None:
        data = await session.execute(
            select(Device)
            .where(Device.sn == sn)
            .where(Device.is_deleted == False)
            .where(DeviceOrgBind.org_id == org_id)
        )
        r = data.unique().one_or_none()
        if r is not None:
            resp = r.Device.device_id
        else:
            resp = None
        return resp

    @classmethod
    async def get_exist_device_sn(cls, session, sn_list):
        lu_q = select(Device.sn).where(not_(Device.sn.in_(sn_list)))
        lu = await session.execute(lu_q)
        lu1 = lu.scalars().all()
        log.info("## device repo get exist devices = %s", lu1)
        return lu1

    @classmethod
    async def add_devices(cls, session: AsyncSession, device_list: Any):
        insert_stmt = (
            insert(Device)
            .values(
                [
                    {"device_id": int(d["device_id"]), "sn": d["serial_number"]}
                    for d in device_list
                ]
                # device_id=21,# sn="a1b21c22589d100424",
            )
            .on_conflict_do_nothing()
        )
        insert_stmt1 = (
            insert(Org)
            .values([{"org_id": int(d["org_id"])} for d in device_list])
            .on_conflict_do_nothing()
        )
        insert_stmt2 = (
            insert(DeviceOrgBind)
            .values(
                [
                    {"device_id": int(d["device_id"]), "org_id": int(d["org_id"])}
                    for d in device_list
                ]
            )
            .on_conflict_do_nothing()
        )
        insert_dev_conn = (
            insert(DeviceConnection)
            .values(
                [
                    {"device_id": int(d["device_id"]), "client_id": d["serial_number"]}
                    for d in device_list
                ]
            )
            .on_conflict_do_nothing()
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
        for dev_con in device_conn:
            con_upd = (
                update(DeviceConnection)
                .values(
                    checked_at=func.current_timestamp(),
                    last_checked_result=True,
                    details=dev_con.details,
                    connected_at=func.to_timestamp(dev_con.connected_at / 1000),
                )
                .where(DeviceConnection.client_id == dev_con.client_id)
            )
            await session.execute(con_upd)
        await session.commit()

    @classmethod
    async def reset_connection_flag(cls, session: AsyncSession, sn_arr: list[str]):
        await session.execute(
            update(DeviceConnection)
            .values(last_checked_result=False)
            .where(DeviceConnection.client_id.in_(sn_arr))
        )
        await session.commit()

    @classmethod
    async def list(cls, session):
        sn_arr_q = select(DeviceConnection.client_id)
        sn_arr = await session.execute(sn_arr_q)
        lu2 = sn_arr.scalars().all()
        log.info("#### device repo list device as scalar select: %s", lu2)
        return lu2

    @classmethod
    async def upsert_tag(cls, session, org_id, device_id, tag, value) -> int:
        stmt = (
            insert(DeviceTag)
            .values(device_id=device_id, tag=tag, value=value)
            .on_conflict_do_update(
                constraint="uq_tb_device_tags_device_id", set_=dict(value=value)
            )
            .returning(DeviceTag.id)
        )
        res = await session.execute(stmt)
        await session.commit()
        tag_id = res.unique().scalars().one()
        return tag_id

    @classmethod
    async def upsert_gauge(cls, session, org_id, device_id, type, gauges) -> int:
        stmt = (
            insert(DeviceGauge)
            .values(device_id=device_id, type=type, gauges=gauges)
            .on_conflict_do_update(
                constraint="uq_tb_device_gauges_device_id_type_is_deleted",
                set_=dict(gauges=gauges, updated_at=func.now()),
            )
            .returning(DeviceGauge.id)
        )
        res = await session.execute(stmt)
        await session.commit()
        gauge_id = res.unique().scalars().one()
        return gauge_id

    # async def add_event(cls, session: AsyncSession, event: DevEventBody) -> None:
    #     evt_q = DevEvent(
    #         **event.model_dump(exclude={"dev_timestamp"}),
    #         dev_timestamp=func.to_timestamp(event.dev_timestamp),
    #     )
    #     session.add(evt_q)
    #     await session.commit()
