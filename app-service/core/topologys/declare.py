import logging
import asyncio
from typing import List, Tuple
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from aio_pika import RobustExchange, RobustQueue
from aiormq import ChannelClosed, ConnectionClosed
from faststream.rabbit import RabbitExchange, ExchangeType, RabbitQueue
from core import settings
from core.fs_broker import fs_router

# Настройка логгера
from core.logging_config import setup_module_logger

log = setup_module_logger(__name__, "topology_declare.log")
logging.getLogger("aio_pika").setLevel(logging.WARNING)
logging.getLogger("aiormq").setLevel(logging.WARNING)


# === Топология RMQ ===
topology = settings.rmq

# Обменники (amq.* существуют по умолчанию)
topic_exchange = RabbitExchange(
    name=topology.x_name, type=ExchangeType.TOPIC, declare=False
)
direct_exchange = RabbitExchange(
    name=topology.x_name_direct, type=ExchangeType.DIRECT, declare=False
)

# Публикаторы
job_publisher = fs_router.publisher(exchange=direct_exchange)
topic_publisher = fs_router.publisher(exchange=topic_exchange)

# Очереди
q_ack = RabbitQueue(
    name=topology.ack_queue_name, durable=True, arguments=topology.def_queue_args
)
q_req = RabbitQueue(
    name=topology.req_queue_name, durable=True, arguments=topology.def_queue_args
)
q_evt = RabbitQueue(name=topology.evt_queue_name, durable=True)
q_result = RabbitQueue(name=topology.res_queue_name, durable=True)
q_jobs = RabbitQueue(
    name=settings.ttl_job.queue_name, durable=False, arguments=topology.job_queue_args
)
rmq_api_client_action = RabbitQueue(
    name=topology.api_clients_queue,
    durable=False,
    arguments=topology.def_queue_args,
)
webhook_action = RabbitQueue(
    name=settings.webhook.webhooks_queue,
    durable=False,
    arguments=settings.webhook.def_queue_args,
)

# Список биндингов: (queue, routing_key, exchange)
BINDINGS: List[Tuple[RabbitQueue, str, RabbitExchange]] = [
    (q_req, topology.routing_key_dev_request, topic_exchange),
    (q_ack, topology.routing_key_dev_ack, topic_exchange),
    (q_evt, topology.routing_key_dev_event, topic_exchange),
    (q_result, topology.routing_key_dev_result, topic_exchange),
    (q_jobs, settings.ttl_job.queue_name, direct_exchange),
    (rmq_api_client_action, topology.api_clients_queue, direct_exchange),
    (webhook_action, settings.webhook.webhooks_queue, direct_exchange),
]


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, max=10),
    retry=retry_if_exception_type((ConnectionClosed, ChannelClosed)),
    reraise=True,
    before_sleep=lambda retry_state: log.warning(
        f"🔁 Попытка {retry_state.attempt_number} не удалась при объявлении топологии RMQ. Повтор через {retry_state.next_action.sleep} сек."
    ),
)
async def declare_x_q():
    """
    Объявление обменников, очередей и их привязка с поддержкой retry и таймаутов.
    """
    log.info("🔄 Начинаем объявление RMQ топологии...")

    broker = fs_router.broker

    try:
        # Удаляем прямую проверку _channel и _connection — это protected members

        # Декларация exchange
        topic_ex: RobustExchange = await asyncio.wait_for(
            broker.declare_exchange(topic_exchange), timeout=10.0
        )
        direct_ex: RobustExchange = await asyncio.wait_for(
            broker.declare_exchange(direct_exchange), timeout=10.0
        )

        exchange_map = {
            topology.x_name: topic_ex,
            topology.x_name_direct: direct_ex,
        }

        for rabbit_queue, routing_key, exchange in BINDINGS:
            try:
                robust_queue: RobustQueue = await asyncio.wait_for(
                    broker.declare_queue(rabbit_queue), timeout=10.0
                )
                real_exchange = exchange_map[exchange.name]
                await robust_queue.bind(
                    exchange=real_exchange,
                    routing_key=routing_key,
                )
                log.debug(
                    f"✅ Привязана очередь '{rabbit_queue.name}' к '{exchange.name}' с ключом '{routing_key}'"
                )
            except Exception as e:
                log.error(
                    f"❌ Не удалось объявить или привязать очередь '{rabbit_queue.name}': {e}"
                )
                raise  # Пробрасываем для активации retry

        # Обновляем публикаторы
        topic_publisher.exchange = topic_exchange
        job_publisher.exchange = direct_exchange

        log.info("✅ RMQ топология успешно объявлена и привязана.")
    except (ConnectionClosed, ChannelClosed) as e:
        log.error(f"🔗 Соединение с RabbitMQ разорвано: {e}")
        raise
    except asyncio.TimeoutError as e:
        log.error("⏰ Таймаут при взаимодействии с RabbitMQ")
        raise
    except Exception as e:
        log.error(f"💥 Непредвиденная ошибка при объявлении топологии: {e}")
        raise
