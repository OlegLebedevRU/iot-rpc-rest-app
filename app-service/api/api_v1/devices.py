import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.api_v1.api_depends import Org_dep
from core import settings
from core.models import db_helper
from core.schemas.devices import DeviceTagPut
from core.services.devices import DeviceService

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
    org_id: Org_dep,
    device_id: Annotated[int | None, Query()] = None,
):
    return await DeviceService.get_list(session, org_id, device_id)


@router.put("/{device_id}", description="Add Device tags")
async def add_device_tag(
    session: Annotated[AsyncSession, Depends(db_helper.session_getter)],
    org_id: Org_dep,
    device_id: int,
    device_tag: DeviceTagPut,
):
    tag_id = await DeviceService.proxy_upsert_tag(
        session, org_id, device_id, device_tag.tag, device_tag.value
    )
    return {"tag_id": tag_id}
