from datetime import datetime
from sqlalchemy import Integer, func, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import TIMESTAMP, JSON
from sqlalchemy.orm import Mapped, mapped_column

from core.models import Base


class DevEvent(Base):
    # __tablename__ = "tb_dev_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    event_type_code: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    dev_event_id: Mapped[int] = mapped_column(Integer, index=True, nullable=True)
    created_at = mapped_column(
        TIMESTAMP(timezone=True, precision=3),
        server_default=func.current_timestamp(3),
        default=None,
    )
    dev_timestamp: Mapped[int] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    payload: Mapped[str] = mapped_column(JSON)


class DeviceEventOffset(Base):
    __tablename__ = "tb_device_event_offsets"
    __table_args__ = (
        UniqueConstraint("device_id", name="uq_device_event_offset_device_id"),
    )
    device_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tb_devices.device_id"), primary_key=True
    )
    last_event_id: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
