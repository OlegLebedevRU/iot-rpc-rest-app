from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi_pagination import Page
from sqlalchemy.ext.asyncio import AsyncSession

from api.api_v1.api_depends import Org_dep
from core.models import db_helper
from core.schemas.devices import DeviceGaugesView
from core.services.devices import DeviceService
from core.logging_config import setup_module_logger

log = setup_module_logger(__name__, "api_gauges.log")

router = APIRouter(
    prefix="/gauges",
    tags=["Gauges"],
)


@router.get(
    "/",
    description="Get paginated list of gauges for devices in organization.",
    response_model=Page[DeviceGaugesView],
)
async def list_gauges(
    session: Annotated[AsyncSession, Depends(db_helper.session_getter)],
    org_id: Org_dep,
    device_id: int | None = None,
    type: str | None = None,
) -> Page[DeviceGaugesView]:
    """
    Получить gauges по устройствам в организации.
    - **device_id**: опционально, фильтр по ID устройства.
    - **type**: опционально, фильтр по типу gauge (например, '44').
    """
    # service = DeviceService(session=session, org_id=org_id)
    return await DeviceService.get_gauges(
        session=session, org_id=org_id, device_id=device_id, type=type
    )
