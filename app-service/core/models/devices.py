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
    Index,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, JSONB
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from core.models import Base
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models import Postamat
from core.models.webhook import OrgWebhook


class Device(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(Integer, unique=True)
    sn: Mapped[str] = mapped_column(String, unique=True, index=True)
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
    org_bind: Mapped["DeviceOrgBind"] = relationship(
        "DeviceOrgBind",
        back_populates="device_bind",
        cascade="all, delete-orphan",
        passive_deletes=True,
        single_parent=True,
        uselist=False,
    )
    device_tags: Mapped[List["DeviceTag"]] = relationship(
        back_populates="tags",
        # lazy="joined",
        primaryjoin="and_(Device.device_id==DeviceTag.device_id, DeviceTag.is_deleted ==sql.false())",
    )
    device_gauges: Mapped[List["DeviceGauge"]] = relationship(
        back_populates="r_gauges",
        primaryjoin="and_(Device.device_id==DeviceGauge.device_id, DeviceGauge.is_deleted ==sql.false())",
        # lazy="selectin",
    )
    # Новая обратная связь с Postamat (1:1)
    postamat: Mapped["Postamat"] = relationship(
        "Postamat",
        back_populates="device",
        cascade="all, delete-orphan",
        passive_deletes=True,
        single_parent=True,
        uselist=False,
    )


class DeviceTag(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(Integer, ForeignKey(Device.device_id))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.current_timestamp(0),
        default=None,
        deferred=True,
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, server_default=sql.false(), deferred=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
        server_onupdate=func.current_timestamp(0),
        deferred=True,
    )
    deleted_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True, deferred=True
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
        TIMESTAMP(timezone=True),
        server_default=func.current_timestamp(0),
        default=None,
        deferred=True,
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, server_default=sql.false(), deferred=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
        server_onupdate=func.current_timestamp(0),
    )
    deleted_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True, deferred=True
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
    # interval_sec: Mapped[int] = query_expression()


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
    # Определение индекса на поле client_id
    # CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tb_device_connections_client_id ON tb_device_connections(client_id)

    __table_args__ = (
        Index("ix_tb_device_connections_client_id", "client_id"),
        # Если нужно — уникальный индекс (если client_id уникален):
        UniqueConstraint("client_id", name="uq_tb_device_connections_client_id"),
    )
    device_conn: Mapped["Device"] = relationship(
        back_populates="connection",
        single_parent=True,
        uselist=False,
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
    webhooks: Mapped[List["OrgWebhook"]] = relationship(
        "OrgWebhook",
        back_populates="org",
        cascade="all, delete-orphan",
        passive_deletes=True,
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
