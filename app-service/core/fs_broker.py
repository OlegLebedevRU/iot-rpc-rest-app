__all__ = (
    "broker",
    "task_registered",
)

from faststream.rabbit import RabbitBroker

from core.config import settings

broker = RabbitBroker(
    str(settings.faststream.url),
)

task_registered = broker.publisher(
    routing_key="device.a3b0000000c99999d250813.task",
)