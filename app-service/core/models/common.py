import enum
from typing import Any, Annotated

from sqlalchemy import Enum, Integer, String, select, delete, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from core.models import Base


# Helper classes
class TaskTTL(enum.IntEnum):
    MIN_TTL = 1
    MAX_TTL = 44640  # = 1 month in minutes


class TaskStatus(enum.IntEnum):
    READY = 0
    PENDING = 1
    LOCK = 2
    DONE = 3
    EXPIRED = 4
    DELETED = 5
    FAILED = 6
    UNDEFINED = 7


class PersistentVariable(Base):
    # __tablename__ = "tb_variables"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    var_key: Mapped[str] = mapped_column(String, nullable=False)
    var_val: Mapped[str] = mapped_column(String, default="NULL")
    var_typ: Mapped[str] = mapped_column(String, default="STR")

    @classmethod
    async def get_data(
        cls, session: AsyncSession, key_val: str | None = "DEFAULT"
    ) -> RowMapping | None:
        data = await session.execute(
            select(cls.var_val.label("var_val"), cls.var_typ.label("var_typ"))
            .where(cls.var_key == key_val)
            .order_by(cls.id.desc())
            .limit(1)
        )
        r = data.mappings().one_or_none()

        return r

    @classmethod
    async def upsert_data(
        cls,
        session: AsyncSession,
        key_val: str | None = "DEFAULT",
        val_var: str | None = "NULL",
        val_typ: str | None = "STR",
    ) -> None:
        await session.execute(delete(cls).where(cls.var_key == key_val))

        await session.commit()
        var = cls(var_key=key_val, var_val=val_var, var_typ=val_typ)
        session.add(var)

        await session.commit()
