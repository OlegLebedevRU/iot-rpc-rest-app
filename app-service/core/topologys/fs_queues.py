import logging
import uuid
from typing import Annotated

from aio_pika import RobustExchange, RobustQueue
from fastapi import Depends
from faststream.rabbit import RabbitExchange, ExchangeType, RabbitQueue
from faststream.rabbit.fastapi import RabbitMessage
from sqlalchemy.ext.asyncio import AsyncSession


from core import settings
from core.config import RoutingKey, TaskProcessingConfig
from core.crud.dev_tasks_repo import TasksRepository
from core.fs_broker import fs_router, broker
from core.models import db_helper
from core.models.common import TaskStatus

job_publisher = fs_router.publisher()
topic_publisher = fs_router.publisher()
topology =  settings.rmq
topic_exchange=RabbitExchange(
            name=topology.x_name,
            type=ExchangeType.TOPIC,
            declare=False
        )
def_x = RabbitExchange(
            name="amq.direct",

            declare=False
        )
q_ack=RabbitQueue(
    name=topology.ack_queue_name,
    durable=True)
q_req=RabbitQueue(
    name=topology.req_queue_name,
    durable=True)
q_evt=RabbitQueue(
    name=topology.evt_queue_name,
    durable=True)
q_result=RabbitQueue(
    name=topology.res_queue_name,
    durable=True)
q_jobs=RabbitQueue(
    name="core_jobs",
    durable=False)
async def declare_x_q():
    amq_ex: RobustExchange = await fs_router.broker.declare_exchange(topic_exchange)
    topic_publisher.exchange = topic_exchange

    # queues
    req_queue: RobustQueue = await broker().declare_queue(q_req)
    ack_queue: RobustQueue = await fs_router.broker.declare_queue(q_ack)
    evt_queue: RobustQueue = await broker().declare_queue(q_evt)
    res_queue: RobustQueue = await broker().declare_queue(q_result)

    await req_queue.bind(exchange=amq_ex, routing_key=topology.routing_key_dev_request,)
    await ack_queue.bind(exchange=amq_ex, routing_key=topology.routing_key_dev_ack)
    await evt_queue.bind(exchange=amq_ex,routing_key=topology.routing_key_dev_event)
    await res_queue.bind(exchange=amq_ex,routing_key=topology.routing_key_dev_result)

    def_ex: RobustExchange = await broker().declare_exchange(def_x)
    jobs_queue: RobustQueue = await broker().declare_queue(q_jobs)
    await jobs_queue.bind(exchange=def_ex,routing_key="core_jobs")
    job_publisher.exchange = def_x
#test_broker = broker()

 # {'x-correlation-id': b'\x96\xce\xe8\xd2\xf4\x1fK_\x81\xcc|w\x0bu\x92\xae',
# 'x-reply-to-topic': 'srv.a3b0000000c99999d250813.rsp'}

@fs_router.subscriber(q_ack)
async def ack(body: str,
              msg: RabbitMessage, session: Annotated[AsyncSession, Depends(db_helper.session_getter)],):
    sn = msg.raw_message.routing_key[4:-4]
    logging.info(f"on_message <dev.{sn}.ack>, body = {body}")
    try:
        task_id = uuid.UUID(bytes=msg.raw_message.headers['x-correlation-id'])
        logging.info(f"srv - in ack exist corr data =  {task_id}")
        if task_id == settings.task_proc_cfg.zero_corr_id:
            task_id = None
    except (TypeError, ValueError, KeyError) as e:
        logging.info(f"srv - in ack from device no corr data, exception = {e}")
        task_id = None
    if task_id is not None:
        await TasksRepository.task_status_update(session, task_id, TaskStatus.PENDING)

    pass


@fs_router.subscriber(q_req)
async def req(body: str,
              msg: RabbitMessage, session: Annotated[AsyncSession, Depends(db_helper.session_getter)],):
    sn = msg.raw_message.routing_key[4:-4]
    logging.info(f"on_message <dev.{sn}.req>, body = {body}")
    try:
        task_id = uuid.UUID(bytes=msg.raw_message.headers['x-correlation-id'])
        logging.info(f"srv - in request exist corr data =  {task_id}")
        if task_id == settings.task_proc_cfg.zero_corr_id:
            task_id = None
    except (TypeError, ValueError, KeyError) as e:
        logging.info(f"srv - in request from device no corr data, exception = {e}")
        task_id = None

    # print(str(msg.raw_message.headers['x-reply-to-topic']))
    task = await TasksRepository.select_task(session, task_id, sn)
    if task is not None:
        t_resp = task.model_dump_json()
        logging.info(f"srv task select = {t_resp}")
        corr_id = task.id
    else:
        t_resp = settings.task_proc_cfg.nop_resp
        logging.info("srv task select = None")
        corr_id=settings.task_proc_cfg.zero_corr_id
    await topic_publisher.publish(
        routing_key=str(RoutingKey(prefix=topology.prefix_srv,
                                   sn=sn,
                                   suffix=topology.suffix_response)),
        message=t_resp,
        correlation_id=corr_id,#msg.raw_message.headers['x-correlation-id'], #task_id.bytes,
        exchange=settings.rmq.x_name
    )
    if task is not None:
        await TasksRepository.task_status_update(session, task.id, TaskStatus.LOCK)

@fs_router.subscriber(q_jobs)
async def jobs_parse(msg: str, session: Annotated[AsyncSession, Depends(db_helper.session_getter),], ):
    await TasksRepository.update_ttl(session, 1)
    logging.info(f"subscribe job event  {msg}")

async def act_ttl(step:int):
    await job_publisher.publish(message="ttl_decrement", routing_key="core_jobs")

