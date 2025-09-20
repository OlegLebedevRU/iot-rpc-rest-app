import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core import settings
from core.models import db_helper

log = logging.getLogger(__name__)
router = APIRouter(
    prefix=settings.api.v1.devices,
    tags=["Devices"],
)


@router.get(
    "/",
    description="Devices status",
)
async def devices(
    session: Annotated[AsyncSession, Depends(db_helper.session_getter)],
    device_ids: list[str] = None,
):
    pass
