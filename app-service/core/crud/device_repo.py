from sqlalchemy import select
from sqlalchemy.ext.asyncio.session import AsyncSession

from core.models import Device


class DeviceRepo():

    @classmethod
    async def get_device_sn(cls, session: AsyncSession, device_id: int | None = 0) -> str | None:
        data = await session.execute(select(Device)
                                     .where(Device.device_id == device_id))
        r = data.mappings().one_or_none()
        #print(str(dict(r).keys()))
        #return "a3b0000000c99999d250813"
        if r is not None:
            resp = r.Device.sn
        else:
            resp = None
        return resp

    @classmethod
    async def get_device_id(cls, session: AsyncSession, sn: str | None = "") -> int | None:
        data = await session.execute(select(Device)
                                     .where(Device.sn == sn))
        r = data.first()
        if r:
            resp = r.device_id
        else:
            resp = None
        return resp
