"""Opt-in fault tests against a disposable PostgreSQL, never production."""

import asyncio
import os

import pytest
from core.models.db_helper import DatabaseHelper
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.environ.get("CAMERA_TEST_DB_URL"),
        reason="Disposable PostgreSQL not supplied",
    ),
]


async def test_command_timeout_and_backend_disconnect_recover():
    db = DatabaseHelper(
        url=os.environ["CAMERA_TEST_DB_URL"],
        pool_size=1,
        max_overflow=0,
        pool_timeout=1,
        connect_args={"timeout": 2, "command_timeout": 0.2},
    )
    try:
        with pytest.raises((TimeoutError, DBAPIError)):
            async with db.session_factory() as session, session.begin():
                await session.execute(text("SELECT pg_sleep(5)"))
        async with db.session_factory() as session:
            assert (await session.execute(text("SELECT 1"))).scalar() == 1
        with pytest.raises(DBAPIError):
            async with db.session_factory() as session, session.begin():
                await session.execute(
                    text("SELECT pg_terminate_backend(pg_backend_pid())")
                )
        async with db.session_factory() as session:
            assert (await session.execute(text("SELECT 1"))).scalar() == 1
    finally:
        await asyncio.wait_for(db.dispose(), 3)
