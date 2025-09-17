from aio_pika import RobustExchange, RobustQueue
from faststream.rabbit import RabbitExchange, ExchangeType, RabbitQueue
from faststream.rabbit.fastapi import RabbitMessage
from core import settings
from core.fs_broker import fs_router, broker
from core.services.device_events import DeviceEventsService
from core.services.device_tasks import (
    DeviceTasksService,
    topic_publisher,
    job_publisher,
    topology,
)
from core.topologys.fs_depends import (
    Session_dep,
    Corr_id_dep,
    Sn_dep,
)

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
    exclusive=True,
    arguments=settings.rmq.def_queue_args,
)


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
    await jobs_queue.bind(exchange=def_ex, routing_key=settings.ttl_job.queue_name)
    job_publisher.exchange = def_x


# {'x-correlation-id': b'\x96\xce\xe8\xd2\xf4\x1fK_\x81\xcc|w\x0bu\x92\xae',
# 'x-reply-to-topic': 'srv.a3b0000000c99999d250813.rsp'}


@fs_router.subscriber(q_evt)
async def add_one_event(
    msg: RabbitMessage,
    session: Session_dep,
    sn: Sn_dep,
):
    await DeviceEventsService(session, sn, 0).add(msg)


@fs_router.subscriber(q_ack)
async def ack(
    session: Session_dep,
    corr_id: Corr_id_dep,
):
    await DeviceTasksService(session, 0).pending(corr_id)


@fs_router.subscriber(q_req)
async def req(
    session: Session_dep,
    sn: Sn_dep,
    corr_id: Corr_id_dep,
):
    await DeviceTasksService(session, 0).select(sn, corr_id)


@fs_router.subscriber(q_result)
async def result(
    msg: RabbitMessage,
    session: Session_dep,
    sn: Sn_dep,
    corr_id: Corr_id_dep,
):
    await DeviceTasksService(session, 0).save(msg, sn, corr_id)


@fs_router.subscriber(q_jobs)
async def jobs_parse(session: Session_dep):
    await DeviceTasksService(session, 0).ttl(decrement=1)
