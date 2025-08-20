from sqlalchemy import Integer, String, select, ForeignKey, BigInteger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from core.models import Base


class Device(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(Integer, unique=True)
    sn: Mapped[str] = mapped_column(String,default="a0b9999901c11111d250820")
    #__tablename__ = "tb_devices"
    # id = Column(Integer, primary_key=True)
    # device_id = Column(Integer, unique=True)
    # sn = Column(String, unique=True, default="default serial number")

    @classmethod
    async def get_device_sn(cls, session: AsyncSession, device_id: int | None = 0) -> str | None:
        data = await session.execute(select(cls.sn.label('sn'))
                                     .where(cls.device_id == device_id))
        r = data.first()
        if r:
            resp = r[0]
        else:
            resp = None
        return resp

class DeviceConnect(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(Integer, ForeignKey(Device.device_id))
    connected_ns: Mapped[int] = mapped_column(BigInteger)
    checked_ns: Mapped[int] = mapped_column(BigInteger)