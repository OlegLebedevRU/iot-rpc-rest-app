import logging
from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from core import settings
from core.models import db_helper
from core.services.rmq_admin import RmqAdmin

log = logging.getLogger(__name__)
router = APIRouter(
    prefix=settings.api.v1.admin,
    tags=["Administrator"],
    include_in_schema=False,
)


@router.post(
    "/",
    description="Server admin",
)
async def do_admin(
    session: Annotated[AsyncSession, Depends(db_helper.session_getter)],
    action: str | None,
    dry_run: Annotated[
        bool,
        Query(
            description="Preview mode for action=get_d/get_u (no DB/RabbitMQ writes)",
        ),
    ] = False,
):
    if action == "get_d":
        # Expected replication item format from factory API:
        # {"device_id": int, "serial_number": str, "org_id": int}
        result = await RmqAdmin.repl_devices(session, settings.leo4.api_key, dry_run=dry_run)
        if dry_run:
            return {"action": action, "dry_run": dry_run, "result": result}
    elif action == "get_u":
        result = await RmqAdmin.set_device_definitions(session, dry_run=dry_run)
        if dry_run:
            return {"action": action, "dry_run": dry_run, "result": result}
