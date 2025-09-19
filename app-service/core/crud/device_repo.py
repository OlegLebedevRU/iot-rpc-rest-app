from sqlalchemy import select, not_
from sqlalchemy.ext.asyncio.session import AsyncSession
from core.models import Device
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
    async def det_exist_device_sn(cls, session, sn_list):
        lu_q = select(Device.sn).where(not_(Device.sn.in_(sn_list)))
        lu = await session.execute(lu_q)
        lu1 = lu.mappings().all()
        print(lu1)
