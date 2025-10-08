from fastapi import APIRouter

from core.config import settings
from .accounts import accounts

from .device_tasks import router as device_tasks_router
from .administrator import router as admin_router
from .device_events import router as device_events_router
from .devices import router as devices_router
from .accounts import router as accounts_router

router = APIRouter(
    prefix=settings.api.v1.prefix,
)
router.include_router(device_tasks_router)

router.include_router(device_events_router)
router.include_router(devices_router)
router.include_router(admin_router, include_in_schema=True)
router.include_router(accounts_router)
