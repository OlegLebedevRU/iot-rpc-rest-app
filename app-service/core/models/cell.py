from datetime import datetime
from sqlalchemy import Integer, String, ForeignKey, Boolean, TIMESTAMP, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.models import Base
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models import Postamat


class Cell(Base):
    __tablename__ = "tb_cells"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    postamat_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tb_postamats.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # порядковый номер ячейки (в пределах постамата)
    size_code: Mapped[str] = mapped_column(
        String, nullable=False
    )  # например, "XL", "20x50"
    alias: Mapped[str] = mapped_column(String, nullable=True)  # опциональный псевдоним
    is_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=True
    )  # True=закрыта, False=открыта, None=неизвестно
    attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=True
    )  # дополнительные свойства
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
        server_onupdate="now()",
    )

    # Уникальность номера ячейки внутри одного постамата
    __table_args__ = (
        UniqueConstraint(
            "postamat_id", "number", name="uq_tb_cells_postamat_id_number"
        ),
    )

    # Связь с Postamat
    postamat: Mapped["Postamat"] = relationship(
        "Postamat",
        back_populates="cells",
        single_parent=True,
        uselist=False,
        innerjoin=True,
    )
