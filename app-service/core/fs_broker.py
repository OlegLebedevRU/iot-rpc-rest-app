# __all__ = ("broker", "fs_router")


from faststream.rabbit.fastapi import RabbitRouter, RabbitBroker
from core.config import settings
from core.logging_config import setup_module_logger

log = setup_module_logger(__name__, "broker_core.log")

# Логируем первый запуск
print(f"🔧 Creating RabbitRouter for {settings.faststream.url}")
log.info(f"Initializing RabbitRouter with URL: {settings.faststream.url}")
# Явно создаём брокер с нужными параметрами
rabbit_broker = RabbitBroker(
    url=str(settings.faststream.url),
    logger=log,
    max_retries=3,
    retry_delay=2,
)

# Передаём брокер в роутер
fs_router = RabbitRouter(rabbit_broker)


def broker():
    return fs_router.broker
