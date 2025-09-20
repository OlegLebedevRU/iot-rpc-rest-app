from typing import Any
from sqlalchemy import select, not_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio.session import AsyncSession
from core.models import Device, DeviceConnection
from core.models.devices import DeviceOrgBind
from core.models.orgs import Org


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
        print(lu1)

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
        insert_dev_conn = insert(DeviceConnection).values([
                    {"device_id": int(d["device_id"]), "client_id": d["serial_number"]}
                    for d in device_list
                ]).on_conflict_do_nothing()

        await session.execute(insert_stmt)
        await session.execute(insert_stmt1)
        await session.execute(insert_stmt2)
        await session.execute(insert_dev_conn)
        await session.commit()
