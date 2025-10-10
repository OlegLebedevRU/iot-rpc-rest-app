__all__ = ("broker", "fs_router")

import logging

from faststream.rabbit.fastapi import RabbitRouter
from core.config import settings

logging.basicConfig(
    level=logging.WARNING,
    format=settings.logging.log_format,
    datefmt=settings.logging.date_format,
    filename="/var/log/app/broker.log",
    filemode="w",
)
log = logging.getLogger(__name__)
fs_router = RabbitRouter(
    str(settings.faststream.url),
    include_in_schema=False,
    logger=log,
    # log_level=logging.WARNING,
    # log_fmt=settings.logging.log_format,
    max_consumers=settings.faststream.max_consumers,
)


def broker():
    return fs_router.broker
