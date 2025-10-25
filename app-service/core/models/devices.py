from datetime import datetime
from typing import List

from sqlalchemy import (
    Integer,
    String,
    ForeignKey,
    Boolean,
    func,
    sql,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship, query_expression
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
    connection: Mapped["DeviceConnection"] = relationship(
        back_populates="device_conn",
        # lazy="joined",
        # primaryjoin="Device.device_id==DeviceConnection.device_id",
    )
    # org_bind: Mapped["DeviceOrgBind"] = relationship(
    #     back_populates="device_bind",
    #     # lazy="noload",
    #     uselist=False,
    #     single_parent=True,
    #     innerjoin=True,
    # )
    device_tags: Mapped[List["DeviceTag"]] = relationship(
        back_populates="tags",
        # lazy="joined",
        # primaryjoin="Device.device_id==DeviceTag.device_id",
    )
    device_gauges: Mapped[List["DeviceGauge"]] = relationship(
        back_populates="r_gauges",
        lazy="selectin",
    )


class DeviceTag(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(Integer, ForeignKey(Device.device_id))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.current_timestamp(0), default=None
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, server_default=sql.false())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
        server_onupdate=func.current_timestamp(0),
    )
    deleted_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    tag: Mapped[str] = mapped_column(String)
    value: Mapped[str] = mapped_column(String, nullable=True)
    is_system_tag: Mapped[bool] = mapped_column(Boolean, server_default=sql.false())
    UniqueConstraint(
        device_id,
        tag,
        is_deleted,
        # name="uq_tb_device_tags_device_id",
        # postgresql_where=(is_deleted == sql.false()),
    )
    tags: Mapped["Device"] = relationship(
        back_populates="device_tags",
        single_parent=True,
        uselist=False,
        innerjoin=True,
        # secondaryjoin="Device.device_id==DeviceTag.device_id",
    )


class DeviceGauge(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(Integer, ForeignKey(Device.device_id))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.current_timestamp(0), default=None
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, server_default=sql.false())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
        server_onupdate=func.current_timestamp(0),
    )
    deleted_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    type: Mapped[str] = mapped_column(String)
    gauges: Mapped[str] = mapped_column(JSONB, nullable=True)
    UniqueConstraint(
        device_id,
        type,
        is_deleted,
        # name="uq_tb_device_tags_device_id",
        # postgresql_where=(is_deleted == sql.false()),
    )
    r_gauges: Mapped["Device"] = relationship(
        back_populates="device_gauges",
        single_parent=True,
        uselist=False,
        innerjoin=True,
        # secondaryjoin="Device.device_id==DeviceTag.device_id",
    )
    interval_sec: Mapped[int] = func.now - updated_at


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
    device_conn: Mapped["Device"] = relationship(
        back_populates="connection",
        # secondaryjoin="Device.device_id==DeviceConnection.device_id",
        single_parent=True,
        uselist=False,
        # secondaryjoin="and_(DeviceOrgBind.org_id==Org.org_id, Org.is_deleted ==sql.false())",
        # innerjoin=True,
    )


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
    o_bind: Mapped["DeviceOrgBind"] = relationship(
        back_populates="org",
        # lazy="joined",
    )


class DeviceOrgBind(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(Device.device_id), unique=True
    )
    org_id: Mapped[int] = mapped_column(Integer, ForeignKey(Org.org_id))
    device_bind: Mapped["Device"] = relationship(
        # back_populates="org_bind",
        single_parent=True,
        lazy="noload",
        innerjoin=True,
    )
    org: Mapped["Org"] = relationship(
        back_populates="o_bind",
        single_parent=True,
        # lazy="joined",
        # join_depth=1,
        # primaryjoin="and_(DeviceOrgBind.org_id==Org.org_id, Org.is_deleted ==sql.false())",
        # primaryjoin="DeviceOrgBind.org_id==Org.org_id",
        innerjoin=True,
    )
