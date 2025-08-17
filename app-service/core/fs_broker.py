__all__ = (
    "broker",
    "task_registered",
)

from faststream.rabbit import RabbitBroker

from core.config import settings

broker = RabbitBroker(
    settings.faststream.url,
)

task_registered = broker.publisher(
    "tasks.{task_id}.created",
)