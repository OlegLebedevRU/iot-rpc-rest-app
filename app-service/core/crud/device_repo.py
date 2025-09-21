import logging
from typing import Any
from sqlalchemy import select, not_, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy import update
from core.models import Device, DeviceConnection, Org
from core.models.devices import DeviceOrgBind
from core.schemas.devices import DeviceConnectStatus

log = logging.getLogger(__name__)


class DeviceRepo:

    @classmethod
    async def get_device_sn(
        cls, session: AsyncSession, device_id: int | None = 0, org_id: int | None = 0
    ) -> str | None:
        data = await session.execute(
            select(Device, DeviceOrgBind, Org.org_id)
            .where(Device.device_id == device_id)
            .where(Device.is_deleted == False)
            .join(DeviceOrgBind, Device.device_id == DeviceOrgBind.device_id)
            .where(DeviceOrgBind.org_id == org_id)
            .join(Org, Org.org_id == DeviceOrgBind.org_id)
            .where(Org.is_deleted == False)
        )
        r = data.mappings().one_or_none()
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
            select(Device, DeviceOrgBind, Org.org_id)
            .where(Device.sn == sn)
            .where(Device.is_deleted == False)
            .join(DeviceOrgBind, Device.device_id == DeviceOrgBind.device_id)
            .where(DeviceOrgBind.org_id == org_id)
            .join(Org, Org.org_id == DeviceOrgBind.org_id)
            .where(Org.is_deleted == False)
        )
        r = data.one_or_none()
        if r is not None:
            resp = r.Device.device_id
        else:
            resp = None
        return resp

    @classmethod
    async def get_exist_device_sn(cls, session, sn_list):
        lu_q = select(Device.sn).where(not_(Device.sn.in_(sn_list)))
        lu = await session.execute(lu_q)
        lu1 = lu.mappings().all()
        log.info("get exist devices = %s", lu1)

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
        lu1 = sn_arr.mappings().all()
        lu2 = [s["client_id"] for s in lu1]
        return lu2
