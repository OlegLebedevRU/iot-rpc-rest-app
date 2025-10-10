__all__ = ("broker", "fs_router")

import logging

from faststream.rabbit.fastapi import RabbitRouter
from core.config import settings


log = logging.getLogger(__name__)
fh = logging.FileHandler("/var/log/app/broker.log")
fh.setLevel(logging.WARNING)
log.addHandler(fh)

fs_router = RabbitRouter(
    str(settings.faststream.url),
    include_in_schema=False,
    logger=log,
    # log_level=logging.WARNING,
    log_fmt=settings.logging.log_format,
    max_consumers=settings.faststream.max_consumers,
)


def broker():
    return fs_router.broker
