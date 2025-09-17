from fastapi_pagination import Page
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi_pagination.ext.sqlalchemy import paginate
from core.models import DevEvent
from core.schemas.device_events import DevEventBody, DevEventOut


class EventRepository:
    @classmethod
    async def add_event(cls, session: AsyncSession, event: DevEventBody) -> None:
        evt_q = DevEvent(
            **event.model_dump(exclude={"dev_timestamp"}),
            dev_timestamp=func.to_timestamp(event.dev_timestamp),
        )
        session.add(evt_q)
        await session.commit()

    @classmethod
    async def get_events_page(
        cls, session: AsyncSession, device_id: int | None
    ) -> Page[DevEventOut]:
        return await paginate(
            session,
            select(DevEvent)
            .where(DevEvent.device_id == device_id)
            .order_by(DevEvent.created_at.desc()),
        )
