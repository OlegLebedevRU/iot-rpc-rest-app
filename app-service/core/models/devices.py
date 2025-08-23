from sqlalchemy import Integer, String, select, ForeignKey, BigInteger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship, backref

from core.models import Base


class Device(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(Integer, unique=True)
    sn: Mapped[str] = mapped_column(String,nullable=True)
    conn = relationship(
        "DeviceConnection", backref=backref("dev_conn", cascade="all, delete-orphan")
    )
    #__tablename__ = "tb_devices"
    # id = Column(Integer, primary_key=True)
    # device_id = Column(Integer, unique=True)
    # sn = Column(String, unique=True, default="default serial number")

class DeviceConnection(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(Integer, ForeignKey(Device.device_id),unique=True)
    connected_at: Mapped[int] = mapped_column(Integer)
    checked_at: Mapped[int] = mapped_column(Integer)
    dev_conn = relationship("Device", cascade="all, delete-orphan")