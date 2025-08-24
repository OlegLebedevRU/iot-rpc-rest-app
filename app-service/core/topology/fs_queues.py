import uuid
from typing import Annotated

from aio_pika import RobustExchange, RobustQueue
from fastapi import Depends
from faststream.rabbit import RabbitExchange, ExchangeType, RabbitQueue
from faststream.rabbit.fastapi import RabbitMessage
from sqlalchemy.ext.asyncio import AsyncSession


from core import settings
from core.config import RoutingKey
from core.crud.dev_tasks_repo import TasksRepository
from core.fs_broker import fs_router, broker
from core.models import db_helper

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
    routing_key=topology.routing_key_dev_ack,
    durable=True)
q_req=RabbitQueue(
    name=topology.req_queue_name,
    routing_key=topology.routing_key_dev_request,
    durable=True)
q_evt=RabbitQueue(
    name=topology.evt_queue_name,
    routing_key=topology.routing_key_dev_event,
    durable=True)
q_result=RabbitQueue(
    name=topology.res_queue_name,
    routing_key=topology.routing_key_dev_result,
    durable=True)
q_jobs=RabbitQueue(
    name="core_jobs",
    routing_key="core_jobs",
    durable=False)
async def declare_exchange():
    amq_ex: RobustExchange = await broker().declare_exchange(topic_exchange)
    def_ex: RobustExchange = await broker().declare_exchange(def_x)
    topic_publisher.exchange = topic_exchange
    job_publisher.exchange = def_x

    # queues
    req_queue: RobustQueue = await broker().declare_queue(q_req)
    ack_queue: RobustQueue = await broker().declare_queue(q_ack)
    evt_queue: RobustQueue = await broker().declare_queue(q_evt)
    res_queue: RobustQueue = await broker().declare_queue(q_result)
    jobs_queue: RobustQueue = await broker().declare_queue(q_jobs)

    await jobs_queue.bind(exchange=def_ex)
    await req_queue.bind(exchange=amq_ex)
    await ack_queue.bind(exchange=amq_ex)
    await evt_queue.bind(exchange=amq_ex)
    await res_queue.bind(exchange=amq_ex)


#test_broker = broker()

@fs_router.subscriber(q_req)
async def req(body : str,
               msg: RabbitMessage):
    try:
        task_id = uuid.UUID(bytes=msg.raw_message.headers['x-correlation-id'])
        print(f"corr data =  {task_id}")
    except (TypeError, ValueError,KeyError) as e:
        print(f"no corr data, exception = {e}")
        task_id = None

    print(body, msg.raw_message.routing_key[4:-4])
    #print(msg)
    # print(str(msg.raw_message.headers['x-reply-to-topic']))
    print(str(uuid.UUID(bytes=msg.raw_message.headers['x-correlation-id'])))
    #return f"Received and responsed from app: {body}"
    #msg.raw_message.headers['x-reply-to-topic']
    await topic_publisher.publish(
         routing_key=str(RoutingKey(prefix=topology.prefix_srv,
                                    sn=msg.raw_message.routing_key[4:-4],
                                    suffix=topology.suffix_response)),
         message=f"response, req body ={body}"
    )

@fs_router.subscriber(q_jobs)
async def jobs_parse(msg:str,session: Annotated[AsyncSession,Depends(db_helper.session_getter),],):
    await TasksRepository.update_ttl(session,1)
    print(msg)

 # {'x-correlation-id': b'\x96\xce\xe8\xd2\xf4\x1fK_\x81\xcc|w\x0bu\x92\xae',
# 'x-reply-to-topic': 'srv.a3b0000000c99999d250813.rsp'}


async def act_ttl(step:int):
    await job_publisher.publish(message="ttl_decrement", routing_key="core_jobs")

