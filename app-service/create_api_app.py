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
from fastapi_pagination import add_pagination
from starlette.responses import HTMLResponse

from core import settings
from core.fs_broker import broker
from core.models import db_helper
from core.services.device_tasks import act_ttl

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    scheduler = AsyncIOScheduler()
    scheduler.configure(
        jobstores={
            "default": MemoryJobStore()
            #    'default': SQLAlchemyJobStore(url=db_url2)
        }
    )
    try:
        scheduler.add_job(
            act_ttl,
            args=[settings.ttl_job.tick_interval],
            coalesce=True,
            # misfire_grace_time=10,
            trigger=IntervalTrigger(minutes=settings.ttl_job.tick_interval),
            id=settings.ttl_job.id_name,
            replace_existing=True,
        )
        scheduler.start()
    except Exception as e:
        logging.info(f"Исключение scheduler: {str(e)}")

    # await broker().start()
    # 'default': MemoryJobStore()

    # # startup
    # if not broker.is_worker_process:
    #     await broker.startup()

    # FastStream broker
    # await broker.start()

    yield
    # shutdown
    await db_helper.dispose()
    scheduler.shutdown()

    # FastStream broker
    await broker().stop()

    # if not broker.is_worker_process:

    # await broker().stop()


def register_static_docs_routes(app: FastAPI) -> None:
    @app.get("/docs", include_in_schema=False)
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

    @app.get("/redoc", include_in_schema=False)
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
        title="Leo4",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
        docs_url=None if create_custom_static_urls else "/docs",
        redoc_url=None if create_custom_static_urls else "/redoc",
    )
    add_pagination(app)
    if create_custom_static_urls:
        register_static_docs_routes(app)
    return app
