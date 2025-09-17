from typing import Any
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from core.models import Device
from core.models.devices import DeviceOrgBind
from core.models.orgs import Org


class AdminRepo:
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
        await session.execute(insert_stmt)
        await session.execute(insert_stmt1)
        await session.execute(insert_stmt2)
        await session.commit()
