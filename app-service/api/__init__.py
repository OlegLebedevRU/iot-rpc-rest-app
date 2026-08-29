from fastapi import APIRouter

from core.config import settings
from .api_v1 import router as router_api_v1
from .internal_v1 import router as router_internal_v1

router = APIRouter(
    prefix=settings.api.prefix,
)
router.include_router(router_api_v1)
router.include_router(router_internal_v1, include_in_schema=False)