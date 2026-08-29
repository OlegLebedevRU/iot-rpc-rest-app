from typing import Annotated, List
from fastapi import APIRouter
from fastapi.params import Query
from fastapi_pagination import Page

from api.internal_v1.internal_depends import Internal_Org_dep, Session_dep
from core import settings
from core.logging_config import setup_module_logger
from core.schemas.device_events import (
    DevEventOut,
    DevEventFields,
    DevEventFieldsRequest,
)
from core.services.device_events import DeviceEventsService

log = setup_module_logger(__name__, "api_internal_device_events.log")
router = APIRouter(
    prefix=settings.api.internal_v1.device_events,
    tags=["Internal Device Events"],
    include_in_schema=False,
)


@router.get(
    "/",
    description="Events search by device_id with pagination",
    response_model=Page[DevEventOut],
)
async def list_device_events(
    device_id: Annotated[int, Query()],
    session: Session_dep,
    org_id: Internal_Org_dep,
    events_include: Annotated[list[int] | None, Query()] = None,
    events_exclude: Annotated[list[int] | None, Query()] = None,
) -> Page[DevEventOut] | None:
    return await DeviceEventsService(session, None, org_id).list(
        device_id, events_include, events_exclude
    )


@router.get(
    "/incremental",
    description="Get incremental events.",
    response_model=List[DevEventOut],
)
async def get_incremental_events(
    session: Session_dep,
    org_id: Internal_Org_dep,
    device_id: Annotated[int | None, Query()] = None,
    last_event_id: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> List[DevEventOut]:
    return await DeviceEventsService(
        session, None, org_id=org_id
    ).get_incremental_events(device_id, last_event_id, limit)


@router.get(
    "/fields/",
    description="Fields select from events.",
    response_model=List[DevEventFields],
)
async def get_event_fields(
    session: Session_dep,
    org_id: Internal_Org_dep,
    request: Annotated[DevEventFieldsRequest, Query()],
) -> List[DevEventFields]:
    return await DeviceEventsService(session, None, org_id).fields(
        request.device_id,
        request.event_type_code,
        request.tag,
        request.interval_m,
        request.limit,
    )
