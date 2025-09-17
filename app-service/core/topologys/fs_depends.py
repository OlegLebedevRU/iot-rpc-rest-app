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
            logging.info("Raw corr_id = %s", msg.correlation_id)
            corr_id = uuid.UUID(msg.correlation_id)
            logging.info("Received msg.correlation_id = %s", corr_id)
        else:
            corr_id = None
        logging.info("Received headers =  %s", msg.raw_message.headers)
        if "x-correlation-id" in msg.raw_message.headers:
            corr_id = uuid.UUID(
                bytes=(msg.raw_message.headers["x-correlation-id"].encode())
            )
            logging.info("Received headers.x-correlation-id =  %s", corr_id)
        else:
            if corr_id is None:
                pass
        if corr_id == settings.task_proc_cfg.zero_corr_id:
            logging.info("settings.task_proc_cfg.zero_corr_id =  %s", corr_id)

    except (TypeError, ValueError, KeyError) as e:
        logging.info("Received from device no corr data, exception = %s", e)
        corr_id = None
    return corr_id
