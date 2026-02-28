from datetime import datetime
from typing import List

from sqlalchemy import Integer, String, ForeignKey, TIMESTAMP, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.models import Base
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models import Device, Cell


class Postamat(Base):
    __tablename__ = "tb_postamats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tb_devices.device_id"), unique=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    address: Mapped[str] = mapped_column(String, nullable=True)
    location: Mapped[dict] = mapped_column(
        JSONB, nullable=True
    )  # {lat: float, lon: float}
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
        server_onupdate="now()",
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # Связь с устройством (1:1)
    device: Mapped["Device"] = relationship(
        "Device",
        back_populates="postamat",
        single_parent=True,
        uselist=False,
        innerjoin=True,
    )
    # Связь один-ко-многим: у одного постамата — много ячеек
    cells: Mapped[List["Cell"]] = relationship(
        "Cell",
        back_populates="postamat",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
