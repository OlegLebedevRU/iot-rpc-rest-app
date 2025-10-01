from fastapi import APIRouter

from .pg_default import router as default_page_router
from .pg_main import router as pg_main_router

router = APIRouter(
    prefix="/pages",
)
router.include_router(default_page_router)
router.include_router(pg_main_router)
