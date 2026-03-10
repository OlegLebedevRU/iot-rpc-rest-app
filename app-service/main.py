import logging

# import uvicorn

# from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings

logging.basicConfig(
    level=settings.logging.log_level_value,
    format=settings.logging.log_format,
)
# from core.fs_broker import fs_router
# from core.topologys.declare import declare_x_q
from create_api_app import create_app

# import core.topologys.fs_queues

# from create_page_app import create_app as create_page_app
# from pages import router as pg_router


main_app = create_app(
    create_custom_static_urls=True,
)

# --- ЗАКОММЕНТИРОВАНО: page_app больше не используется ---
# page_app = create_page_app()
# main_app.mount("/web", page_app)
# page_app.include_router(
#    pg_router,
# )
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
main_app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# if __name__ == "__main__":
#     uvicorn.run(
#         "main:main_app",
#         host=settings.run.host,
#         port=settings.run.port,
#         reload=True,
#     )
