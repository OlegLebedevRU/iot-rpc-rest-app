from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import DevEvent
from core.schemas.device_events import DevEventBody, DevEvents


class EventRepository:
    @classmethod
    async def add_event(cls, session: AsyncSession, event: DevEventBody) -> None:
        evt_q = DevEvent(
            **event.model_dump(exclude={"dev_timestamp"}),
            dev_timestamp=func.to_timestamp(event.dev_timestamp),
        )
        session.add(evt_q)
        await session.commit()
