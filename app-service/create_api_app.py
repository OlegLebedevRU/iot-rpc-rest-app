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
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi_pagination import add_pagination
from api import router as api_router
from core import settings
from core.fs_broker import fs_router
from core.logging_config import setup_module_logger
from core.models import db_helper
from core.services.device_task_processing import act_ttl
from core.topologys.declare import declare_x_q
import core.topologys.fs_queues

# from starlette.responses import HTMLResponse

log = setup_module_logger(__name__, "app_create_app.log")
logging.getLogger("logger_proxy").disabled = True


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:

    await fs_router.broker.start()
    await declare_x_q()  # ← здесь
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
        log.info(f"Исключение scheduler: {str(e)}")

    yield

    await db_helper.dispose()
    scheduler.shutdown()

    # FastStream broker
    await fs_router.broker.close()


# @fs_router.after_startup
# async def declare_topology(app: FastAPI):
#     await declare_x_q()


def register_static_docs_routes(app: FastAPI) -> None:
    @app.get("/docs", include_in_schema=False)
    async def custom_swagger_ui_html() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=str(app.openapi_url),
            title=app.title + " - Swagger UI",
            oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
            swagger_js_url="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js",
            swagger_css_url="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css",
            swagger_favicon_url="/favicon.ico",
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
        default_response_class=JSONResponse,
        lifespan=lifespan,
        docs_url="/docs" if create_custom_static_urls else "/legacy-docs",
        redoc_url=None if create_custom_static_urls else "/redoc",
    )
    add_pagination(app)
    app.include_router(
        api_router,
    )
    app.include_router(
        fs_router,
    )
    if create_custom_static_urls:
        register_static_docs_routes(app)

    return app
