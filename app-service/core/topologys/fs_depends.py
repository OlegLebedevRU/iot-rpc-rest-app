import logging
import uuid
from faststream.rabbit.fastapi import RabbitMessage
from core import settings


async def sn_getter_dep(msg: RabbitMessage) -> str:
    logging.info("Mqtt received topic= <%s>", msg.raw_message.routing_key)
    return msg.raw_message.routing_key[4:-4]


async def corr_id_getter_dep(msg: RabbitMessage) -> str | None:
    try:
        if msg.correlation_id:
            corr_id = uuid.UUID(msg.correlation_id)
            logging.info("Received msg.correlation_id = %s", corr_id)
        elif hasattr(msg.raw_message.headers, "x-correlation-id"):
            corr_id = uuid.UUID(bytes=msg.raw_message.headers["x-correlation-id"])
            logging.info("Received headers.x-correlation-id =  %s", corr_id)
            if corr_id == settings.task_proc_cfg.zero_corr_id:
                corr_id = None
        else:
            corr_id = None
    except (TypeError, ValueError, KeyError) as e:
        logging.info("Received from device no corr data, exception = %s", e)
        corr_id = None
    return corr_id
