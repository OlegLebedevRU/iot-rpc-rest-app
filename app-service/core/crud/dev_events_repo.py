from core.logging_config import setup_module_logger
from typing import Optional, List

from fastapi_pagination import Page
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import text, and_, or_, select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi_pagination.ext.sqlalchemy import apaginate
from core.models import DevEvent, DeviceOrgBind
from core.models.device_events import DeviceEventOffset
from core.schemas.device_events import DevEventBody, DevEventOut

log = setup_module_logger(__name__, "repo_dev_events.log")


class EventRepository:
    @classmethod
    async def add_event(cls, session: AsyncSession, event: DevEventBody) -> bool:
        """
        Сохраняет событие. Возвращает True если событие новое,
        False если дубликат по (device_id, dev_event_id) — идемпотентная обработка.
        Raises на прочие ошибки.
        """
        evt_q = DevEvent(
            **event.model_dump(exclude={"dev_timestamp"}),
            dev_timestamp=func.to_timestamp(event.dev_timestamp),
        )
        session.add(evt_q)
        try:
            await session.commit()
            return True
        except IntegrityError as e:
            await session.rollback()
            if "uq_dev_event_idempotent" in str(e.orig):
                log.info(
                    "Idempotent duplicate: device_id=%d dev_event_id=%d — skipped",
                    event.device_id,
                    event.dev_event_id,
                )
                return False
            log.error(f"Ошибка при сохранении события: {e}")
            raise
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
            return await apaginate(
                session,
                select(DevEvent)
                .where(
                    DevEvent.device_id == device_id,
                    DevEvent.event_type_code.in_(events_include),
                )
                .order_by(DevEvent.created_at.desc()),
            )
        else:
            return await apaginate(
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
        limit: int | None = 50,
    ):
        interval_m = 15 if interval_m is None or interval_m > 3600 else interval_m
        limit = 50 if limit is None else min(limit, 100)
        stmt = text("""
                    SELECT
                        created_at,
                        COALESCE(
                            payload -> '300' -> 0 -> :tag,
                            payload -> :tag
                        ) AS value,
                        EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - created_at))::INTEGER AS interval_sec
                    FROM tb_dev_events
                    WHERE
                        device_id = :did
                        AND event_type_code = :etc
                        AND created_at > CURRENT_TIMESTAMP - MAKE_INTERVAL(mins => CAST(:mins AS INTEGER))
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
        return result.mappings().all()

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
        Использует FOR UPDATE для предотвращения race condition и SQL-агрегацию для производительности.
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

            # Блокируем offset-записи для предотвращения race condition
            offsets_stmt = (
                select(DeviceEventOffset)
                .where(DeviceEventOffset.device_id.in_(target_device_ids))
                .with_for_update()
            )
            offsets_result = await session.execute(offsets_stmt)
            offsets = {
                offset.device_id: offset.last_event_id
                for offset in offsets_result.scalars().all()
            }

            # Формируем условие: id > max(last_event_id, offset)
            if last_event_id is not None:
                base_id = last_event_id
                conditions = [
                    DevEvent.device_id.in_(target_device_ids),
                    DevEvent.id > base_id,
                ]
            else:
                conditions = [
                    DevEvent.device_id.in_(target_device_ids),
                    or_(
                        *[
                            and_(
                                DevEvent.device_id == dev_id,
                                DevEvent.id > offsets.get(dev_id, 0),
                            )
                            for dev_id in target_device_ids
                        ]
                    ),
                ]

            # Получаем события, отсортированные по id
            events_stmt = (
                select(DevEvent)
                .where(*conditions)
                .order_by(DevEvent.id.asc())
                .limit(limit)
            )
            events_result = await session.execute(events_stmt)
            events = events_result.scalars().all()

            if not events:
                return []

            # Используем SQL для нахождения max(id) по каждому device_id
            update_offsets_stmt = (
                select(
                    DevEvent.device_id,
                    func.max(DevEvent.id).label("max_id"),
                )
                .where(DevEvent.id.in_([ev.id for ev in events]))
                .group_by(DevEvent.device_id)
            )
            offsets_update_result = await session.execute(update_offsets_stmt)
            # Явно конвертируем результат в словарь {device_id: max_id}
            new_offsets = {
                row.device_id: row.max_id for row in offsets_update_result.mappings()
            }

            # Подготавливаем upsert для offset
            for dev_id, max_id in new_offsets.items():
                current_offset = offsets.get(dev_id, 0)
                if max_id <= current_offset:
                    continue

                upsert_stmt = (
                    insert(DeviceEventOffset)
                    .values(device_id=dev_id, last_event_id=max_id)
                    .on_conflict_do_update(
                        index_elements=["device_id"],
                        set_=dict(last_event_id=max_id),
                    )
                )
                await session.execute(upsert_stmt)

            await session.commit()

            return [
                DevEventOut.model_validate(event, from_attributes=True)
                for event in events
            ]

        except Exception as e:
            await session.rollback()
            log.error(
                f"Ошибка при получении инкрементальных событий: org_id={org_id}, "
                f"device_id={device_id}, last_event_id={last_event_id}, {e}"
            )
            raise
