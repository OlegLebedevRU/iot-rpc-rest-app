from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from api.api_v1.api_depends import Org_dep
from core import settings
from core.logging_config import setup_module_logger
from core.models import db_helper
from core.schemas.devices import DeviceTagPut, DeviceListResponse
from core.services.devices import DeviceService

# from starlette.requests import Request

log = setup_module_logger(__name__, "api_devices.log")
router = APIRouter(
    prefix=settings.api.v1.devices,
    tags=["Devices"],
)


@router.get("/", description="Devices status", response_model=DeviceListResponse)
async def devices(
    session: Annotated[AsyncSession, Depends(db_helper.session_getter)],
    org_id: Org_dep,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    device_id: int | None = Query(default=None),
    sort_by: str = Query(default="device_id"),
    sort_order: str = Query(default="asc"),
):
    return await DeviceService.get_list(
        session=session,
        org_id=org_id,
        device_id=device_id,
        page=page,
        size=size,
        q=q,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.put("/{device_id}", description="Add Device tags")
async def add_device_tag(
    session: Annotated[AsyncSession, Depends(db_helper.session_getter)],
    org_id: Org_dep,
    device_id: int,
    device_tag: DeviceTagPut,
):
    tag_id = await DeviceService.proxy_upsert_tag(
        session, org_id, device_id, device_tag
    )
    return {"tag_id": tag_id}
