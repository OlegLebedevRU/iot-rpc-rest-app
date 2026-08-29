from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi_pagination import Page
from sqlalchemy.ext.asyncio import AsyncSession

from api.internal_v1.internal_depends import Internal_Org_dep, Session_dep
from core.schemas.devices import DeviceGaugesView
from core.services.devices import DeviceService
from core.logging_config import setup_module_logger
from core import settings

log = setup_module_logger(__name__, "api_internal_gauges.log")
router = APIRouter(
    prefix=settings.api.internal_v1.gauges,
    tags=["Internal Gauges"],
    include_in_schema=False,
)


@router.get(
    "/",
    description="Get paginated list of gauges for devices in organization.",
    response_model=Page[DeviceGaugesView],
)
async def list_gauges(
    session: Session_dep,
    org_id: Internal_Org_dep,
    device_id: int | None = None,
    type: str | None = None,
) -> Page[DeviceGaugesView]:
    return await DeviceService.get_gauges(
        session=session, org_id=org_id, device_id=device_id, type=type
    )
