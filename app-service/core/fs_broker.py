__all__ = (
    "broker",
    "task_registered",
    "fs_router"
)

import logging

from aio_pika import RobustExchange,RobustQueue
from fastapi import FastAPI
from faststream.rabbit import ExchangeType, RabbitQueue, RabbitExchange

from faststream.rabbit.fastapi import RabbitRouter, RabbitMessage
from core.config import settings

fs_router = RabbitRouter(str(settings.faststream.url),
                         log_level=settings.logging.log_level_value,
                         log_fmt=settings.logging.log_format,)
task_registered = fs_router.publisher()

def broker():
    return fs_router.broker

rx=RabbitExchange(
            name=settings.rmq.x_name,
            type=ExchangeType.TOPIC,
            declare=False
        )
dq=RabbitQueue(name=settings.rmq.dev_queue_name, durable=True)
@fs_router.after_startup
async def declare_exchange(app: FastAPI):
    amq_ex: RobustExchange = await broker().declare_exchange(rx)
    dev_queue: RobustQueue = await broker().declare_queue(dq)
    await dev_queue.bind(
        exchange=amq_ex,
        routing_key=settings.rmq.routing_key_dev_req  # Optional parameter
    )
@fs_router.subscriber(dq)
async def req(body: str,
              msg: RabbitMessage):
    print(body, msg.raw_message.routing_key[4:-4])