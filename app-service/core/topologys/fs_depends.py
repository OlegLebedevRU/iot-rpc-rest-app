import logging
import uuid
from typing import Annotated

from fastapi import Depends
from faststream.rabbit.fastapi import RabbitMessage
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import db_helper

log = logging.getLogger(__name__)

Session_dep = Annotated[
    AsyncSession,
    Depends(db_helper.session_getter),
]


async def sn_getter_dep(msg: RabbitMessage) -> str:
    log.info(
        "Mqtt received topic= <%s>, headers=%s",
        msg.raw_message.routing_key,
        msg.raw_message.headers,
    )
    return msg.raw_message.routing_key[4:-4]


Sn_dep = Annotated[str, Depends(sn_getter_dep)]


async def corr_id_getter_dep(msg: RabbitMessage) -> str | None:
    try:
        if msg.correlation_id:
            # logging.info("Raw corr_id = %s", msg.correlation_id)
            corr_id = uuid.UUID(msg.correlation_id)
            log.info("Received msg.correlation_id = %s", corr_id)
        else:
            corr_id = None
        # logging.info("Received headers =  %s", msg.raw_message.headers)
        if "x-correlation-id" in msg.raw_message.headers:
            corr_id = uuid.UUID(
                # bytes=(msg.raw_message.headers["x-correlation-id"].encode())
                bytes=(msg.raw_message.headers["x-correlation-id"]).encode()
            )
            log.info("Received headers.x-correlation-id =  %s", corr_id)
        else:
            if corr_id is None:
                pass
        # if corr_id == settings.task_proc_cfg.zero_corr_id:
        #     logging.info("settings.task_proc_cfg.zero_corr_id =  %s", corr_id)

    except (TypeError, ValueError, KeyError) as e:
        log.info("Received from device no corr data, exception = %s", e)
        corr_id = None
    return corr_id


Corr_id_dep = Annotated[str | None, Depends(corr_id_getter_dep)]
