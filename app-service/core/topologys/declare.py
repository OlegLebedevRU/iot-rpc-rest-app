import logging

from core.logging_config import setup_module_logger

from aio_pika import RobustExchange, RobustQueue
from faststream.rabbit import RabbitExchange, ExchangeType, RabbitQueue

from core import settings
from core.fs_broker import fs_router, broker

# from core.services.device_tasks import  topic_publisher, job_publisher

# Настройка логгера
log = setup_module_logger(__name__, "topology_declare.log")

# Отключаем логи от logger_proxy (избыточные "Received", "Processed")
logging.getLogger("logger_proxy").setLevel(logging.WARNING)

topology = settings.rmq
job_publisher = fs_router.publisher()
topic_publisher = fs_router.publisher()


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
    arguments=settings.rmq.job_queue_args,
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
    log.info(f"Declaring topology")
    # declare queues, exchange, bindings
    amq_ex: RobustExchange = await fs_router.broker.declare_exchange(topic_exchange)
    topic_publisher.exchange = topic_exchange
    # queues
    # queue for requests from devices
    req_queue: RobustQueue = await broker().declare_queue(q_req)
    # queue for ack task from device
    ack_queue: RobustQueue = await fs_router.broker.declare_queue(q_ack)
    # events from devices
    evt_queue: RobustQueue = await broker().declare_queue(q_evt)
    # queue for results of tasks from devices
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
    import core.topologys.fs_queues
