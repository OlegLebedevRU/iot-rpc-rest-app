import logging
import time
from typing import Annotated
from aio_pika import RobustExchange, RobustQueue
from fastapi import Depends
from faststream.rabbit import RabbitExchange, ExchangeType, RabbitQueue
from faststream.rabbit.fastapi import RabbitMessage
from sqlalchemy.ext.asyncio import AsyncSession
from core import settings
from core.config import RoutingKey
from core.crud.dev_events_repo import EventRepository
from core.crud.dev_tasks_repo import TasksRepository
from core.crud.device_repo import DeviceRepo
from core.fs_broker import fs_router, broker
from core.models import db_helper
from core.models.common import TaskStatus
from core.schemas.device_events import DevEventBody
from core.topologys.fs_depends import sn_getter_dep, corr_id_getter_dep

job_publisher = fs_router.publisher()
topic_publisher = fs_router.publisher()
topology = settings.rmq
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
    session: Annotated[AsyncSession, Depends(db_helper.session_getter)],
    sn: Annotated[str, Depends(sn_getter_dep)],
):
    try:
        dev_id = await DeviceRepo.get_device_id(session=session, sn=sn)
    except Exception as e:
        logging.info(
            "Mqtt received EVENT: <dev.%s.evt>, error select device_id, error= =%s",
            sn,
            e,
        )
        return
    if dev_id is None:
        return
    if hasattr(msg, "headers"):
        msg_headers = msg.headers
        if "event_type_code" in msg_headers:
            event_type_code = int(msg_headers["event_type_code"])
        else:
            event_type_code = 0
        if "dev_event_id" in msg_headers:
            dev_event_id = int(msg.headers["dev_event_id"])
        else:
            dev_event_id = 0
        if "dev_timestamp" in msg_headers:
            dev_timestamp = msg.headers["dev_timestamp"]
        else:
            dev_timestamp = int(time.time())
        logging.info(
            "Mqtt received EVENT: event_type_code =%d, dev_event_id=%d",
            event_type_code,
            dev_event_id,
        )
        event = DevEventBody(
            device_id=dev_id,
            event_type_code=event_type_code,
            dev_event_id=dev_event_id,
            dev_timestamp=dev_timestamp,
            payload=msg.body.decode(),
        )
        await EventRepository.add_event(session, event)


@fs_router.subscriber(q_ack)
async def ack(
    session: Annotated[AsyncSession, Depends(db_helper.session_getter)],
    corr_id: Annotated[str | None, Depends(corr_id_getter_dep)],
):
    if corr_id is not None:
        await TasksRepository.task_status_update(session, corr_id, TaskStatus.PENDING)


@fs_router.subscriber(q_req)
async def req(
    session: Annotated[AsyncSession, Depends(db_helper.session_getter)],
    sn: Annotated[str, Depends(sn_getter_dep)],
    corr_id: Annotated[str | None, Depends(corr_id_getter_dep)],
):
    task = await TasksRepository.select_task(session, corr_id, sn)
    if task is not None:
        t_resp = task.model_dump_json()
        logging.info("from DB select task = %s", t_resp)
        method_code = str(task.header.method_code)
        await TasksRepository.task_status_update(session, task.id, TaskStatus.LOCK)
        correlation_id = task.id
    else:
        t_resp = settings.task_proc_cfg.nop_resp
        logging.info("from DB select task = None")
        correlation_id = settings.task_proc_cfg.zero_corr_id
        method_code = "0"
    routing_key: str = str(
        RoutingKey(prefix=topology.prefix_srv, sn=sn, suffix=topology.suffix_response)
    )
    await topic_publisher.publish(
        routing_key=routing_key,
        message=t_resp,
        correlation_id=correlation_id,
        exchange=settings.rmq.x_name,
        headers={"method_code": method_code},
    )


@fs_router.subscriber(q_result)
async def result(
    msg: RabbitMessage,
    session: Annotated[AsyncSession, Depends(db_helper.session_getter)],
    sn: Annotated[str, Depends(sn_getter_dep)],
    corr_id: Annotated[str | None, Depends(corr_id_getter_dep)],
):
    if "ext_id" in msg.headers:
        ext_id = int(msg.headers["ext_id"])
    else:
        ext_id = 0
    if "status_code" in msg.headers:
        status_code = int(msg.headers["status_code"])
    else:
        status_code = 501
    if corr_id:
        if msg.body:
            res = msg.body.decode()
        else:
            res = "default"
        logging.info(
            "Mqtt received RESULT ext_id=%d, status_code=%d",
            ext_id,
            status_code,
        )
        await TasksRepository.save_task_result(
            session, corr_id, ext_id, status_code, res
        )
        await TasksRepository.task_status_update(session, corr_id, TaskStatus.DONE)
    else:
        logging.info(
            "Mqtt received RESULT with ERROR <dev.%s.res> - No corr_id, ext_id=%d, status_code=%d",
            sn,
            ext_id,
            status_code,
        )


@fs_router.subscriber(q_jobs)
async def jobs_parse(
    msg: str,
    session: Annotated[
        AsyncSession,
        Depends(db_helper.session_getter),
    ],
):
    await TasksRepository.update_ttl(session, 1)
    logging.info("subscribe job event  %s", msg)


async def act_ttl(step: int):
    await job_publisher.publish(
        message="ttl_decrement", routing_key=settings.ttl_job.queue_name
    )
