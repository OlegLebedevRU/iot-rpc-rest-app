"""PostgreSQL row-lock serialization; missing durable state never self-heals."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import func, or_, select

from core.camera.authority_state import load_state
from core.models.camera_authority import CameraAuthority
from core.models.db_helper import db_helper


class AuthorityStore:
    def __init__(self, sessions=None):
        self.sessions = sessions or db_helper.session_factory

    @asynccontextmanager
    async def locked(self, sn: str) -> AsyncIterator[tuple[CameraAuthority, datetime]]:
        async with self.sessions() as session, session.begin():
            row = await session.scalar(
                select(CameraAuthority)
                .where(CameraAuthority.sn == sn)
                .with_for_update()
            )
            if row is None:
                raise ValueError("camera_authority_not_provisioned")
            now = await session.scalar(select(func.clock_timestamp()))
            row.state = load_state(row.state)
            yield row, now
            # JSONB is assigned a new object so nested edits are always persisted.
            from sqlalchemy.orm.attributes import flag_modified

            flag_modified(row, "state")
            row.state = load_state(row.state)

    async def get(self, sn: str) -> dict:
        async with self.sessions() as session:
            state = await session.scalar(
                select(CameraAuthority.state).where(CameraAuthority.sn == sn)
            )
            if state is None:
                raise ValueError("camera_authority_not_provisioned")
            return load_state(state)

    async def candidates(self) -> list[str]:
        async with self.sessions() as session:
            result = await session.scalars(
                select(CameraAuthority.sn)
                .where(
                    or_(
                        CameraAuthority.owner.is_not(None),
                        CameraAuthority.state["configured"].astext.is_not(None),
                    )
                )
                .order_by(CameraAuthority.owner_until.asc().nullsfirst())
                .limit(256)
            )
            return list(result)
