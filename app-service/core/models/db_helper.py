import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncEngine,
    async_sessionmaker,
    AsyncSession,
)

from core.config import settings

log = logging.getLogger(__name__)


class DatabaseHelper:
    def __init__(
        self,
        url: str,
        echo: bool = False,
        echo_pool: bool = False,
        pool_size: int = 5,
        max_overflow: int = 10,
    ) -> None:
        self.engine: AsyncEngine = create_async_engine(
            url=url,
            echo=echo,
            echo_pool=echo_pool,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
        )
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

    async def dispose(self) -> None:
        await self.engine.dispose()
        log.info("Database engine disposed")

    async def session_getter(self) -> AsyncGenerator[AsyncSession, None]:
        async with self.session_factory() as session:
            yield session


""""
InterfaceError
Exception raised for errors that are related to the database interface rather than the database itself.

This error is a DBAPI Error and originates from the database driver (DBAPI), not SQLAlchemy itself.

The InterfaceError is sometimes raised by drivers in the context of the database connection being dropped, 
or not being able to connect to the database. 
For tips on how to deal with this, see the section Dealing with Disconnects.
https://docs.sqlalchemy.org/en/20/core/pooling.html#dealing-with-disconnects
"""

db_h = DatabaseHelper(
    url=str(settings.db.url),
    echo=settings.db.echo,
    echo_pool=settings.db.echo_pool,
    pool_size=settings.db.pool_size,
    max_overflow=settings.db.max_overflow,
)


def db_init():
    log.info("db init")
    return db_h


db_helper = db_init()
