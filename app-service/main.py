import logging

import uvicorn
from fastapi import FastAPI

from core.config import settings

from api import router as api_router
from core.fs_broker import fs_router
from core.topologys.declare import declare_x_q
from create_api_app import create_app

logging.basicConfig(
    level=settings.logging.log_level_value,
    format=settings.logging.log_format,
)

main_app = create_app(
    create_custom_static_urls=True,
)
main_app.include_router(
    api_router,
)
main_app.include_router(
    fs_router,
)


@fs_router.after_startup
async def declare_topology(main_app: FastAPI):
    await declare_x_q()


if __name__ == "__main__":
    uvicorn.run(
        "main:main_app",
        host=settings.run.host,
        port=settings.run.port,
        reload=True,
    )
