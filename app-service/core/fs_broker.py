__all__ = ("broker", "fs_router")

from faststream.rabbit.fastapi import RabbitRouter
from core.config import settings

fs_router = RabbitRouter(
    str(settings.faststream.url),
    include_in_schema=False,
    log_level=settings.logging.log_level_value,
    log_fmt=settings.logging.log_format,
    max_consumers=settings.faststream.max_consumers,
)


def broker():
    return fs_router.broker
