import logging
from typing import Annotated, List
from fastapi import APIRouter
from fastapi.params import Query
from fastapi_pagination import Page
from api.api_v1.api_depends import Session_dep, Org_dep
from core import settings
from core.schemas.device_events import (
    DevEventOut,
    DevEventFields,
    DevEventFieldsRequest,
)
from core.services.device_events import DeviceEventsService

log = logging.getLogger(__name__)
router = APIRouter(
    prefix=settings.api.v1.device_events,
    tags=["Device events"],
)


@router.get(
    "/",
    description="Events search by device_id with pagination",
    response_model=Page[DevEventOut],
)
async def list_device_events(
    device_id: Annotated[int, Query()],
    session: Session_dep,
    org_id: Org_dep,
    events_include: Annotated[list[int] | None, Query()] = None,
    events_exclude: Annotated[list[int] | None, Query()] = None,
) -> Page[DevEventOut] | None:
    return await DeviceEventsService(session, None, org_id).list(
        device_id, events_include, events_exclude
    )


@router.get(
    "/fields/",
    description="Fields select from events",
    response_model=List[DevEventFields],
)
async def get_event_fields(
    session: Session_dep,
    org_id: Org_dep,
    request: Annotated[DevEventFieldsRequest, Query()],
) -> List[DevEventFields]:
    return await DeviceEventsService(session, None, org_id).fields(
        request.device_id,
        request.event_type_code,
        request.tag,
        request.interval_m,
        request.limit,
    )
