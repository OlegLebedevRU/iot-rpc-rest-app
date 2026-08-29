import logging
from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.internal_v1.internal_depends import Internal_Auth_dep, Session_dep
from core import settings
from core.services.rmq_admin import RmqAdmin

log = logging.getLogger(__name__)
router = APIRouter(
    prefix=settings.api.internal_v1.admin,
    tags=["Internal Administrator"],
    include_in_schema=False,
)


@router.post(
    "/",
    description="Server admin operations",
)
async def do_admin(
    session: Session_dep,
    _: Internal_Auth_dep,
    action: str | None,
    dry_run: Annotated[
        bool,
        Query(
            description="Preview mode for action=get_d/get_u (no DB/RabbitMQ writes)",
        ),
    ] = False,
):
    if action == "get_d":
        result = await RmqAdmin.repl_devices(
            session, settings.leo4.api_key, dry_run=dry_run
        )
        if dry_run:
            return {"action": action, "dry_run": dry_run, "result": result}
    elif action == "get_u":
        result = await RmqAdmin.set_device_definitions(session, dry_run=dry_run)
        if dry_run:
            return {"action": action, "dry_run": dry_run, "result": result}
    return {"status": "ok", "action": action}
