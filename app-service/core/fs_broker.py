# __all__ = ("broker", "fs_router")
import logging

from faststream.rabbit.fastapi import RabbitRouter
from core.config import settings, mask_amqp_url
from core.logging_config import setup_module_logger

log = setup_module_logger(__name__, "broker_core.log")
logging.getLogger("logger_proxy").setLevel(logging.WARNING)
# Log the (possibly rewritten) URL — password is masked for safety.
_masked_url = mask_amqp_url(str(settings.faststream.url))
print(f"🔧 Creating RabbitRouter for {_masked_url}")
log.info("Initializing RabbitRouter with URL: %s", _masked_url)

# FastStream's RabbitRouter uses aio-pika's robust connection internally,
# which will automatically reconnect if the broker disappears at runtime.
# Startup retry/backoff is handled in create_api_app.py lifespan.
fs_router = RabbitRouter(
    url=str(settings.faststream.url),
    logger=log,
    log_level=logging.DEBUG,
    timeout=10.0,
    include_in_schema=False,
)


def broker():
    return fs_router.broker
