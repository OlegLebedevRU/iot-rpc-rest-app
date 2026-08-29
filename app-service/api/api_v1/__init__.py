from fastapi import APIRouter

from core.config import settings

from .device_tasks import router as device_tasks_router
from .device_events import router as device_events_router
from .devices import router as devices_router
from .webhook import router as webhooks_router
from .gauges import router as gauges_router

router = APIRouter(
    prefix=settings.api.v1.prefix,
)
router.include_router(device_tasks_router)
router.include_router(device_events_router)
router.include_router(devices_router)
router.include_router(webhooks_router)
router.include_router(gauges_router)
