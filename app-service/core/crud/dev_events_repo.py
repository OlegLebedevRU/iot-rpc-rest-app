from fastapi_pagination import Page
from sqlalchemy import func, select, text
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
        cls,
        session: AsyncSession,
        device_id: int | None,
        events_include: list[int] | None = None,
        events_exclude: list[int] | None = None,
    ) -> Page[DevEventOut]:
        if events_include is not None:
            return await paginate(
                session,
                select(DevEvent)
                .where(
                    DevEvent.device_id == device_id,
                    DevEvent.event_type_code.in_(events_include),
                )
                .order_by(DevEvent.created_at.desc()),
            )
        else:
            return await paginate(
                session,
                select(DevEvent)
                .where(
                    DevEvent.device_id == device_id,
                    ~DevEvent.event_type_code.in_(
                        events_exclude if events_exclude is not None else []
                    ),
                )
                .order_by(DevEvent.created_at.desc()),
            )

    @classmethod
    async def get_event_fields(
        cls,
        session: AsyncSession,
        device_id: int,
        event_type_code: int,
        tag: int,
        interval_m: int | None,
        limit: int | None = 10,
    ):
        if interval_m is None or interval_m > 3600:
            interval_m = 15
        if limit is None or limit > 10:
            limit = 10
        stmt_txt = text(
            "SELECT created_at, ((payload #>> '{}')::jsonb -> '300'->0->:tag)::text as field,\
                    (EXTRACT(EPOCH FROM current_timestamp - created_at))::Integer AS interval_sec \
                    from tb_dev_events \
                    WHERE device_id = :did and event_type_code = :etc and created_at > current_timestamp - func.cast(concat(:mins, ' MINUTES'), INTERVAL) \
                    order by created_at desc limit :limit"
        )
        result = await session.execute(
            stmt_txt,
            {
                "did": device_id,
                "etc": event_type_code,
                "tag": str(tag),
                "mins": interval_m,
                "limit": limit,
            },
        )
        return result.unique().mappings().all()


#
# """"
# SELECT (payload #>> '{}')::jsonb -> '300'->0->'301' as res, (EXTRACT(EPOCH FROM current_timestamp - created_at)/60)::Integer AS "Minute passes"
# from public.tb_dev_events
# WHERE device_id = 4617 and event_type_code = 3 and created_at > current_timestamp - interval '50000 minutes'
# order by created_at desc limit 1
#
# SELECT (payload #>> '{}')::jsonb -> '300'->0->'338' as res, (EXTRACT(EPOCH FROM current_timestamp - created_at)/60)::Integer AS "Minute passes"
# from public.tb_dev_events
# WHERE device_id = 4618 and event_type_code = 44 and created_at > current_timestamp - interval '15 minutes'
# order by created_at desc limit 1
#
# SELECT created_at, (payload #>> '{}')::jsonb -> '300'->0->'399' as field,
# (EXTRACT(EPOCH FROM current_timestamp - created_at))::Integer AS "interval_sec"
# from public.tb_dev_events
# WHERE device_id = 4618 and event_type_code = 1000 and created_at > current_timestamp - interval '5500 minutes'
# order by created_at desc limit 10
#
# SELECT created_at, ((payload #>> '{}')::jsonb -> '300'->0->'338')::text as field,
# (EXTRACT(EPOCH FROM current_timestamp - created_at))::Integer AS "interval_sec"
# from public.tb_dev_events
# WHERE device_id = 4618 and event_type_code = 44 and created_at > current_timestamp - interval '5500 minutes'
# order by created_at desc limit 10
# """
