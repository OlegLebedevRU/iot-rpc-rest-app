import uuid

from aio_pika import RobustExchange, RobustQueue
from faststream.rabbit import RabbitExchange, ExchangeType, RabbitQueue
from faststream.rabbit.fastapi import RabbitMessage

from core import settings
from core.config import RoutingKey
from core.fs_broker import fs_router, broker

topology =  settings.rmq
topic_publisher = fs_router.publisher()
topic_exchange=RabbitExchange(
            name=topology.x_name,
            type=ExchangeType.TOPIC,
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
async def declare_exchange():
    amq_ex: RobustExchange = await broker().declare_exchange(topic_exchange)
    topic_publisher.exchange = topic_exchange
    # queues
    req_queue: RobustQueue = await broker().declare_queue(q_req)
    ack_queue: RobustQueue = await broker().declare_queue(q_ack)
    evt_queue: RobustQueue = await broker().declare_queue(q_evt)
    res_queue: RobustQueue = await broker().declare_queue(q_result)

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

 # {'x-correlation-id': b'\x96\xce\xe8\xd2\xf4\x1fK_\x81\xcc|w\x0bu\x92\xae',
# 'x-reply-to-topic': 'srv.a3b0000000c99999d250813.rsp'}

