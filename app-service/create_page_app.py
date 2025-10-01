import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.responses import ORJSONResponse
from fastapi.responses import HTMLResponse
from httpx import AsyncClient

from core import settings
from core.fs_broker import broker
from core.models import db_helper
from core.services.device_tasks import act_ttl

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app_: FastAPI):
    async with AsyncClient() as client:
        app_.state.httpx_client = client
        yield


def register_static_docs_routes(app: FastAPI) -> None:
    @app.get("/pages-docs", include_in_schema=False)
    async def custom_swagger_ui_html() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=str(app.openapi_url),
            title=app.title + " - Swagger UI",
            oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
            swagger_js_url="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js",
            swagger_css_url="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css",
        )

    @app.get(str(app.swagger_ui_oauth2_redirect_url), include_in_schema=False)
    async def swagger_ui_redirect() -> HTMLResponse:
        return get_swagger_ui_oauth2_redirect_html()

    @app.get("/pages-redoc", include_in_schema=False)
    async def redoc_html() -> HTMLResponse:
        return get_redoc_html(
            openapi_url=str(app.openapi_url),
            title=app.title + " - ReDoc",
            redoc_js_url="https://unpkg.com/redoc@next/bundles/redoc.standalone.js",
        )


def create_app(
    create_custom_static_urls: bool = False,
) -> FastAPI:
    app = FastAPI(
        title="Leo4-pages",
        default_response_class=HTMLResponse,
        lifespan=lifespan,
        docs_url=None if create_custom_static_urls else "/pages-docs",
        redoc_url=None if create_custom_static_urls else "/pages-redoc",
    )

    if create_custom_static_urls:
        register_static_docs_routes(app)
    return app
