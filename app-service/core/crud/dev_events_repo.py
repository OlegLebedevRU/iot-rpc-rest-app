from core.logging_config import setup_module_logger
from typing import Optional, List

from fastapi_pagination import Page
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import text, and_, or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi_pagination.ext.sqlalchemy import paginate
from core.models import DevEvent, DeviceOrgBind
from core.models.device_events import DeviceEventOffset
from core.schemas.device_events import DevEventBody, DevEventOut

log = setup_module_logger(__name__, "repo_dev_events.log")


class EventRepository:
    @classmethod
    async def add_event(cls, session: AsyncSession, event: DevEventBody) -> None:
        evt_q = DevEvent(
            **event.model_dump(exclude={"dev_timestamp"}),
            dev_timestamp=func.to_timestamp(event.dev_timestamp),
        )
        session.add(evt_q)
        try:
            await session.commit()
        except Exception as e:
            await session.rollback()
            log.error(f"Ошибка при сохранении события: {e}")
            raise

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
        stmt = text("""
                    SELECT 
                        created_at,
                        (payload -> '300' -> 0 ->> :tag) AS value,
                        EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - created_at))::INTEGER AS interval_sec
                    FROM tb_dev_events
                    WHERE 
                        device_id = :did 
                        AND event_type_code = :etc
                        AND created_at > CURRENT_TIMESTAMP - (:mins || ' MINUTES')::INTERVAL
                    ORDER BY created_at DESC 
                    LIMIT :limit
                """)

        result = await session.execute(
            stmt,
            {
                "did": device_id,
                "etc": event_type_code,
                "tag": str(tag),
                "mins": interval_m,
                "limit": limit,
            },
        )
        return result.unique().mappings().all()

    @classmethod
    async def get_incremental_events(
        cls,
        session: AsyncSession,
        org_id: int,
        device_id: Optional[int] = None,
        last_event_id: Optional[int] = None,
        limit: int = 50,
    ) -> List[DevEventOut]:
        """
        Возвращает новые события (id > last_event_id или сохранённого offset).
        Автоматически обновляет смещение в tb_device_event_offsets.
        """
        try:
            # Получаем device_id, принадлежащие орге
            devices_subq = select(DeviceOrgBind.device_id).where(
                DeviceOrgBind.org_id == org_id
            )
            if device_id is not None:
                devices_subq = devices_subq.where(DeviceOrgBind.device_id == device_id)
            devices_result = await session.execute(devices_subq)
            target_device_ids = [r[0] for r in devices_result.fetchall()]
            if not target_device_ids:
                return []

            # Получаем текущие смещения
            offsets_stmt = select(DeviceEventOffset).where(
                DeviceEventOffset.device_id.in_(target_device_ids)
            )
            offsets_result = await session.execute(offsets_stmt)
            offsets = {
                offset.device_id: offset.last_event_id
                for offset in offsets_result.scalars().all()
            }

            # Формируем условия WHERE
            conditions = [DevEvent.device_id.in_(target_device_ids)]

            if last_event_id is not None:
                last_id: int = last_event_id
                conditions.append(and_(DevEvent.id > last_id))
            else:
                or_conds = []
                for dev_id in target_device_ids:
                    last_id = offsets.get(dev_id, 0)
                    or_conds.append(
                        and_(DevEvent.device_id == dev_id, DevEvent.id > last_id)
                    )
                conditions.append(or_(*or_conds))

            # Выбираем события
            stmt = (
                select(DevEvent)
                .where(*conditions)
                .order_by(DevEvent.id.asc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            events = result.scalars().all()

            if not events:
                return []

            # Группируем события по device_id и находим max(id)
            events_by_device = {}
            for ev in events:
                if ev.device_id not in events_by_device:
                    events_by_device[ev.device_id] = []
                events_by_device[ev.device_id].append(ev)

            # Подготавливаем batch upsert для смещений
            for dev_id, ev_list in events_by_device.items():
                max_id = max(ev.id for ev in ev_list)
                current_offset = offsets.get(dev_id, 0)
                if max_id <= current_offset:
                    continue  # не обновляем, если уже было выше

                # Upsert: INSERT ... ON CONFLICT UPDATE
                upsert_stmt = (
                    insert(DeviceEventOffset)
                    .values(device_id=dev_id, org_id=org_id, last_event_id=max_id)
                    .on_conflict_do_update(
                        index_elements=["device_id"],
                        set_=dict(last_event_id=max_id),
                    )
                )
                await session.execute(upsert_stmt)

            await session.commit()

            # Возвращаем Pydantic-модели
            return [
                DevEventOut.model_validate(event, from_attributes=True)
                for event in events
            ]
        except Exception as e:
            await session.rollback()
            log.error(f"Ошибка при получении инкрементальных событий: {e}")
            raise


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
