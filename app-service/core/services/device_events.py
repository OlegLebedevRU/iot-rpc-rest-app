import logging
from typing import Optional, List
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from core.crud.dev_events_repo import EventRepository
from core.logging_config import setup_module_logger

# from core.fs_broker import fs_router
from core.schemas.device_events import (
    DevEventFields,
    DevEventOut,
    UserEventSearchRequest,
    UserEventSearchResponse,
)

log = setup_module_logger(__name__, "srv_dev_evnt.log")
logging.getLogger("logger_proxy").setLevel(logging.WARNING)
# topic_publisher = fs_router.publisher()


class DeviceEventsService:
    def __init__(self, session: AsyncSession, sn: str | None = None, org_id: int = 0):
        self.session: AsyncSession = session
        self.sn = sn
        self.org_id = org_id

    def _require_tenant(self) -> None:
        if self.org_id <= 0:
            raise HTTPException(
                status_code=400, detail="A positive tenant org_id is required"
            )

    async def list(self, device_id, events_include, events_exclude):
        self._require_tenant()
        events = await EventRepository.get_events_page(
            self.session,
            device_id,
            events_include=events_include,
            events_exclude=events_exclude,
            org_id=self.org_id,
        )
        if events is None:
            raise HTTPException(status_code=404, detail="Events not found")
        return events

    async def get_incremental_events(
        self,
        device_id: Optional[int] = None,
        last_event_id: Optional[int] = None,
        limit: int = 50,
    ) -> List[DevEventOut]:
        """
        Получает инкрементальные события.
        Смещение автоматически обновляется внутри репозитория.
        """
        self._require_tenant()
        return await EventRepository.get_incremental_events(
            self.session,
            org_id=self.org_id,
            device_id=device_id,
            last_event_id=last_event_id,
            limit=limit,
        )

    async def fields(self, device_id, event_type_code, tag, interval_m, limit):
        self._require_tenant()
        fields = await EventRepository.get_event_fields(
            self.session,
            device_id,
            event_type_code,
            tag,
            interval_m,
            limit,
            org_id=self.org_id,
        )
        if fields is None:
            raise HTTPException(status_code=404, detail="Fields not found")
        fres: list[DevEventFields] = [
            DevEventFields(
                created_at=f["created_at"],
                value=f["value"],
                interval_sec=f["interval_sec"] if f["interval_sec"] is not None else 0,
            )
            for f in fields
        ]

        return fres

    async def search_user_events(
        self, request: UserEventSearchRequest
    ) -> UserEventSearchResponse:
        self._require_tenant()
        return await EventRepository.search_user_events(
            self.session, self.org_id, request
        )


# """"
# dev_statuses: list[DeviceConnectStatus] = [
#             DeviceConnectStatus(
#                 client_id=d.user,
#                 connected_at=d.connected_at,
#                 last_checked_result=True,
#                 device_id=0,
#                 details=d.model_dump_json(exclude="client_properties"),
#             )
#             for d in dev_online
#         ]
# """


# """
# async def get_event_fields(
#         cls,
#         session: AsyncSession,
#         device_id: int,
#         event_type_code: int,
#         tag: int,
#         interval_m: int | None,
#         limit: int | None = 10,
#     ):
# """
