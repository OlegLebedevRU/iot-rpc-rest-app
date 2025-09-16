import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.params import Query
from fastapi_pagination import Page
from sqlalchemy.ext.asyncio import AsyncSession

from core import settings
from core.crud.dev_events_repo import EventRepository
from core.models import db_helper


from core.schemas.device_events import DevEventOut

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
async def get_device_events(
    device_id: Annotated[int, Query()],
    session: Annotated[AsyncSession, Depends(db_helper.session_getter)],
) -> Page[DevEventOut] | None:  # TaskResponseStatus:
    events = await EventRepository.get_events_page(session, device_id)
    if events is None:
        raise HTTPException(status_code=404, detail="Events not found")
    return events
