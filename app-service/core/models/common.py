import enum
import logging.handlers

from sqlalchemy import Integer, String, select, delete, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from core import settings
from core.models import Base

log = logging.getLogger(__name__)
fh = logging.handlers.RotatingFileHandler(
    "/var/log/app/repo_common.log",
    mode="a",
    maxBytes=10 * 1024 * 1024,
    backupCount=10,
    encoding="utf-8",
)
fh.setLevel(logging.INFO)
formatter = logging.Formatter(settings.logging.log_format)
fh.setFormatter(formatter)
log.addHandler(fh)


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

        try:
            await session.commit()
        except Exception as e:
            log.error("Failed to update key-val: %s", e)
            await session.rollback()
            raise
        var = cls(var_key=key_val, var_val=val_var, var_typ=val_typ)
        session.add(var)

        try:
            await session.commit()
        except Exception as e:
            log.error("Failed to add key-val: %s", e)
            await session.rollback()
            raise
