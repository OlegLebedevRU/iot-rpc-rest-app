from typing import Annotated, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from api.internal_v1.internal_depends import Internal_Org_dep, Session_dep
from core import settings
from core.logging_config import setup_module_logger
from core.schemas.devices import DeviceTagPut, DeviceListResult
from core.services.devices import DeviceService

log = setup_module_logger(__name__, "api_internal_devices.log")
router = APIRouter(
    prefix=settings.api.internal_v1.devices,
    tags=["Internal Devices"],
    include_in_schema=False,
)


@router.get("/", description="Devices status", response_model=List[DeviceListResult])
async def devices(
    session: Session_dep,
    org_id: Internal_Org_dep,
    device_id: Annotated[int | None, Query()] = None,
):
    return await DeviceService.get_list(session, org_id, device_id)


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
