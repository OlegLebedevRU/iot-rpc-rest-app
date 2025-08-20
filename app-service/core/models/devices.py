from sqlalchemy import Integer, String, select, ForeignKey, BigInteger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from core.models import Base


class Device(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(Integer, unique=True)
    sn: Mapped[str] = mapped_column(String,nullable=True)
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

    @classmethod
    async def get_device_id(cls, session: AsyncSession, sn: str | None = "") -> int | None:
        data = await session.execute(select(cls.device_id.label('device_id'))
                                     .where(cls.sn == sn))
        r = data.first()
        if r:
            resp = r[0]
        else:
            resp = None
        return resp

class DeviceConnection(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(Integer, ForeignKey(Device.device_id),unique=True)
    connected_ns: Mapped[int] = mapped_column(BigInteger)
    checked_ns: Mapped[int] = mapped_column(BigInteger)