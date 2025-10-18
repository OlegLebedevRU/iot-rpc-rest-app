import logging
from faststream.rabbit.fastapi import RabbitMessage

from core import settings
from core.fs_broker import fs_router
from core.services.device_events import DeviceEventsService
from core.services.device_tasks import (
    DeviceTasksService,
)
from core.topologys import (
    q_ack,
    q_req,
    q_evt,
    q_result,
)
from core.topologys.fs_depends import Session_dep, Sn_dep, Corr_id_dep


log = logging.getLogger(__name__)
fh = logging.FileHandler("/var/log/app/fs_queues.log")
fh.setLevel(logging.INFO)
formatter = logging.Formatter(settings.logging.log_format)
fh.setFormatter(formatter)

log.addHandler(fh)
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
    msg: RabbitMessage,
    session: Session_dep,
    sn: Sn_dep,
    corr_id: Corr_id_dep,
):
    await DeviceTasksService(session, 0).select(sn, corr_id, msg)


@fs_router.subscriber(q_result)
async def result(
    msg: RabbitMessage,
    session: Session_dep,
    sn: Sn_dep,
    corr_id: Corr_id_dep,
):
    await DeviceTasksService(session, 0).save(msg, sn, corr_id)
