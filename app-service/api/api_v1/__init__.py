from fastapi import APIRouter

from core.config import settings

from .device_tasks import router as device_tasks_router

router = APIRouter(
    prefix=settings.api.v1.prefix,
)
router.include_router(
    device_tasks_router,
    prefix=settings.api.v1.device_tasks,
)