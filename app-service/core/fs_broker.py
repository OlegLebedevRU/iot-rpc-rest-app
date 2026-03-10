# __all__ = ("broker", "fs_router")
import logging

from faststream.rabbit.fastapi import RabbitRouter
from core.config import settings
from core.logging_config import setup_module_logger

log = setup_module_logger(__name__, "broker_core.log")
logging.getLogger("logger_proxy").setLevel(logging.WARNING)
# Логируем первый запуск
print(f"🔧 Creating RabbitRouter for {settings.faststream.url}")
log.info(f"Initializing RabbitRouter with URL: {settings.faststream.url}")

# Передаём параметры напрямую — они поддерживаются в FastStream >=0.5.0


# Передаём брокер в роутер
fs_router = RabbitRouter(
    url=str(settings.faststream.url),
    logger=log,
    log_level=logging.DEBUG,
    # max_retries=None,#
    # max_retries=3,
    # retry_delay=2,
    timeout=10.0,
)


def broker():
    return fs_router.broker
