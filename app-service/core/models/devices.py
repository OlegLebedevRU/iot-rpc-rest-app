from datetime import datetime

from sqlalchemy import (
    Integer,
    String,
    select,
    ForeignKey,
    BigInteger,
    Boolean,
    func,
    DateTime,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, backref

from core.models import Base
from core.models.orgs import Org


class Device(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(Integer, unique=True)
    sn: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.current_timestamp(0), default=None
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    # conn = relationship(
    #     "DeviceConnection", backref=backref("d_conn", single_parent=True, cascade="all, delete-orphan")
    # )
    # __tablename__ = "tb_devices"
    # id = Column(Integer, primary_key=True)
    # device_id = Column(Integer, unique=True)
    # sn = Column(String, unique=True, default="default serial number")


class DeviceOrgBind(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(Device.device_id), unique=True
    )
    org_id: Mapped[int] = mapped_column(Integer, ForeignKey(Org.org_id))


class DeviceConnection(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(Device.device_id), unique=True
    )
    connected_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    checked_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    client_id: Mapped[str] = mapped_column(String, nullable=True)
    last_checked_result: Mapped[bool] = mapped_column(Boolean, default=False)
    details: Mapped[str] = mapped_column(JSONB, default=None)
    dev_conn = relationship("Device", single_parent=True, cascade="all, delete-orphan")
