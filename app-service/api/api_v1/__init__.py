from fastapi import APIRouter

from core.config import settings

from .device_tasks import router as device_tasks_router
from .administrator import router as admin_router

router = APIRouter(
    prefix=settings.api.v1.prefix,
)
router.include_router(device_tasks_router)
router.include_router(admin_router, include_in_schema=True)
