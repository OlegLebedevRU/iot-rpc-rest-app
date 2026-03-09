import logging.handlers

from aio_pika import RobustExchange, RobustQueue
from faststream.rabbit import RabbitExchange, ExchangeType, RabbitQueue

from core import settings
from core.fs_broker import fs_router, broker
from core.services.device_tasks import topology, topic_publisher, job_publisher

# Настройка логгера
log = logging.getLogger(__name__)

# Ротация логов: 10 файлов по 10 МБ
fh = logging.handlers.RotatingFileHandler(
    "/var/log/app/fs_declare.log",
    mode="a",
    maxBytes=10 * 1024 * 1024,
    backupCount=10,
    encoding="utf-8",
)
fh.setLevel(logging.INFO)
formatter = logging.Formatter(settings.logging.log_format)
fh.setFormatter(formatter)
log.addHandler(fh)

# Отключаем логи от logger_proxy (избыточные "Received", "Processed")
logging.getLogger("logger_proxy").setLevel(logging.WARNING)
topic_exchange = RabbitExchange(
    name=topology.x_name, type=ExchangeType.TOPIC, declare=False
)
def_x = RabbitExchange(name=settings.rmq.x_name_direct, declare=False)
q_ack = RabbitQueue(
    name=topology.ack_queue_name,
    durable=True,
    arguments=settings.rmq.def_queue_args,
)
q_req = RabbitQueue(
    name=topology.req_queue_name,
    durable=True,
    arguments=settings.rmq.def_queue_args,
)
q_evt = RabbitQueue(name=topology.evt_queue_name, durable=True)
q_result = RabbitQueue(name=topology.res_queue_name, durable=True)
q_jobs = RabbitQueue(
    name=settings.ttl_job.queue_name,
    durable=False,
    # exclusive=True,
    arguments=settings.rmq.def_queue_args,
)
rmq_api_client_action = RabbitQueue(
    name=settings.rmq.api_clients_queue,
    durable=False,
    # exclusive=True,
    arguments=settings.rmq.def_queue_args,
)
webhook_action = RabbitQueue(
    name=settings.webhook.webhooks_queue,
    durable=False,
    # exclusive=True,
    arguments=settings.webhook.def_queue_args,
)
# webhooks_queue


async def declare_x_q():
    # declare queues, exchange, bindings
    amq_ex: RobustExchange = await fs_router.broker.declare_exchange(topic_exchange)
    topic_publisher.exchange = topic_exchange
    # queues
    req_queue: RobustQueue = await broker().declare_queue(q_req)
    ack_queue: RobustQueue = await fs_router.broker.declare_queue(q_ack)
    evt_queue: RobustQueue = await broker().declare_queue(q_evt)
    res_queue: RobustQueue = await broker().declare_queue(q_result)
    # bind queues to exchange with routing key
    await req_queue.bind(
        exchange=amq_ex,
        routing_key=topology.routing_key_dev_request,
    )
    await ack_queue.bind(exchange=amq_ex, routing_key=topology.routing_key_dev_ack)
    await evt_queue.bind(exchange=amq_ex, routing_key=topology.routing_key_dev_event)
    await res_queue.bind(exchange=amq_ex, routing_key=topology.routing_key_dev_result)

    def_ex: RobustExchange = await broker().declare_exchange(def_x)
    jobs_queue: RobustQueue = await broker().declare_queue(q_jobs)
    rmq_client_action_robust: RobustQueue = await broker().declare_queue(
        rmq_api_client_action
    )
    webhook_robust_queue: RobustQueue = await broker().declare_queue(webhook_action)
    await jobs_queue.bind(exchange=def_ex, routing_key=settings.ttl_job.queue_name)
    await rmq_client_action_robust.bind(
        exchange=def_ex, routing_key=settings.rmq.api_clients_queue
    )
    await webhook_robust_queue.bind(
        exchange=def_ex, routing_key=settings.webhook.webhooks_queue
    )

    job_publisher.exchange = def_x
