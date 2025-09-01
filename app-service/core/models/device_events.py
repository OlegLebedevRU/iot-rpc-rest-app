from datetime import datetime

from sqlalchemy import Integer, func
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
        TIMESTAMP(timezone=True, precision=0),
        server_default=func.current_timestamp(0),
        default=None,
    )
    dev_timestamp: Mapped[int] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    payload: Mapped[str] = mapped_column(JSON)
