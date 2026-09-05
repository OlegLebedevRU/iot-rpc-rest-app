from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from api.internal_v1.internal_depends import Internal_Org_dep, Session_dep
from core import settings
from core.logging_config import setup_module_logger
from core.schemas.devices import DeviceTagPut, DeviceListResponse
from core.services.devices import DeviceService

log = setup_module_logger(__name__, "api_internal_devices.log")
router = APIRouter(
    prefix=settings.api.internal_v1.devices,
    tags=["Internal Devices"],
    include_in_schema=False,
)


@router.get("/", description="Devices status", response_model=DeviceListResponse)
async def devices(
    session: Session_dep,
    org_id: Internal_Org_dep,
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
    session: Session_dep,
    org_id: Internal_Org_dep,
    device_id: int,
    device_tag: DeviceTagPut,
):
    tag_id = await DeviceService.proxy_upsert_tag(
        session, org_id, device_id, device_tag
    )
    return {"tag_id": tag_id}
