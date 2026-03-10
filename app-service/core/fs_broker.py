__all__ = ("broker", "fs_router")


from faststream.rabbit.fastapi import RabbitRouter
from core.config import settings
from core.logging_config import setup_module_logger

log = setup_module_logger(__name__, "broker_core.log")


fs_router = RabbitRouter(
    str(settings.faststream.url),
    include_in_schema=False,
    logger=log,
    # log_level=logging.WARNING,
    # log_fmt=settings.logging.log_format,
    # max_consumers=settings.faststream.max_consumers,
)


def broker():
    return fs_router.broker
