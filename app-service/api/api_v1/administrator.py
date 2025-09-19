import logging
from typing import Annotated
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from core import settings
from core.models import db_helper
from core.services.rmq_admin import RmqAdmin

log = logging.getLogger(__name__)
router = APIRouter(
    prefix=settings.api.v1.admin,
    tags=["Administrator"],
)


@router.post(
    "/",
    description="Server admin",
)
async def do_admin(
    session: Annotated[AsyncSession, Depends(db_helper.session_getter)],
    action: str | None,
):
    if action == "get_d":
        await RmqAdmin.repl_devices(session, settings.leo4.api_key)
    elif action == "get_u":
        await RmqAdmin.set_device_definitions(session)
