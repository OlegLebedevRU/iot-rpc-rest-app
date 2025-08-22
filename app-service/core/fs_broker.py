__all__ = (
    "broker",
    "fs_router"
)

from faststream.rabbit.fastapi import RabbitRouter, RabbitMessage
from core.config import settings
fs_router = RabbitRouter(str(settings.faststream.url),
                         log_level=settings.logging.log_level_value,
                         log_fmt=settings.logging.log_format,)


def broker():
    return fs_router.broker