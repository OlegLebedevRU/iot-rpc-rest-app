from datetime import datetime
from sqlalchemy import (
    Integer,
    String,
    ForeignKey,
    Boolean,
    func,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.models import Base


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
    connection: Mapped["DeviceConnection"] = relationship(back_populates="device")
    org_bind: Mapped["DeviceOrgBind"] = relationship(back_populates="device")


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
    details: Mapped[str] = mapped_column(JSONB, nullable=True)
    device: Mapped["Device"] = relationship(back_populates="connection")


class Org(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.current_timestamp(0), default=None
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    device_bind: Mapped["DeviceOrgBind"] = relationship(back_populates="org")


class DeviceOrgBind(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(Device.device_id), unique=True
    )
    org_id: Mapped[int] = mapped_column(Integer, ForeignKey(Org.org_id))
    device: Mapped["Device"] = relationship(back_populates="org_bind")
    org: Mapped["Org"] = relationship(back_populates="device_bind")
