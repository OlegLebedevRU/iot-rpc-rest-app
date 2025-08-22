from aio_pika import RobustExchange, RobustQueue
from faststream.rabbit import RabbitExchange, ExchangeType, RabbitQueue
from faststream.rabbit.fastapi import RabbitMessage

from core import settings
from core.fs_broker import fs_router, broker

topology =  settings.rmq
topic_publisher = fs_router.publisher()
topic_exchange=RabbitExchange(
            name=topology.x_name,
            type=ExchangeType.TOPIC,
            declare=False
        )
q_req=RabbitQueue(
    name=topology.req_queue_name,
    routing_key=topology.routing_key_dev_request,
    durable=True)

async def declare_exchange():
    amq_ex: RobustExchange = await broker().declare_exchange(topic_exchange)
    req_queue: RobustQueue = await broker().declare_queue(q_req)
    await req_queue.bind(exchange=amq_ex)
    topic_publisher.exchange = topic_exchange
#test_broker = broker()

@fs_router.subscriber(q_req)
async def req(body : str,
               msg: RabbitMessage):
     print(body, msg.raw_message.routing_key[4:-4])
    # print(str(msg.raw_message.headers['x-reply-to-topic']))
    # print(str(uuid.UUID(bytes=msg.raw_message.headers['x-correlation-id'])))
    #return f"Received and responsed from app: {body}"

     await topic_publisher.publish(
         routing_key=msg.raw_message.headers['x-reply-to-topic'],
         message=f"from api with amqp publish, task ={body}"
     )

 # {'x-correlation-id': b'\x96\xce\xe8\xd2\xf4\x1fK_\x81\xcc|w\x0bu\x92\xae',
# 'x-reply-to-topic': 'srv.a3b0000000c99999d250813.rsp'}

