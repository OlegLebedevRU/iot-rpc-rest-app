from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.models.base import Base

if TYPE_CHECKING:
    from core.models.devices import Org


class OrgApiKey(Base):
    __tablename__ = "tb_org_api_keys"

    org_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tb_orgs.org_id", ondelete="CASCADE"),
        primary_key=True,
        unique=True,
        doc="ID организации (1:1)",
    )
    api_key: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        index=True,
        nullable=False,
        doc="Уникальный API-ключ для внешних интеграций",
    )
    name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Описание / Название партнёра или сервиса",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
        doc="Флаг активности ключа",
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )

    org: Mapped["Org"] = relationship("Org", back_populates="api_key_record")
