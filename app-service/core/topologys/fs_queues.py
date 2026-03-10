import logging
import sys
from typing import TYPE_CHECKING

from faststream.rabbit.fastapi import RabbitMessage
from core.fs_broker import fs_router
from core.logging_config import setup_module_logger
from core.services.device_events_collect import DeviceEventsCollect
from core.topologys.declare import q_ack, q_req, q_evt, q_result
from core.topologys.fs_depends import Session_dep, Sn_dep, Corr_id_dep

# Use TYPE_CHECKING to avoid runtime import
if TYPE_CHECKING:
    from core.services.device_tasks import DeviceTasksService

log = setup_module_logger(__name__, "topology_queues.log")

# Отключаем логи от FastStream вида "Received", "Processed"
logging.getLogger("logger_proxy").setLevel(logging.WARNING)


# === Защита от повторной регистрации ===
_SUBSCRIBERS_REGISTERED = False


def _ensure_single_registration():
    global _SUBSCRIBERS_REGISTERED
    if _SUBSCRIBERS_REGISTERED:
        log.warning("Subscribers already registered. Skipping duplicate subscription.")
        return False
    _SUBSCRIBERS_REGISTERED = True
    return True


if not _ensure_single_registration():
    del sys
    exit()


# === Регистрация подписчиков ===
@fs_router.subscriber(q_evt)
async def add_one_event(
    msg: RabbitMessage,
    session: Session_dep,
    sn: Sn_dep,
):
    log.info("Subscribe event queue")
    await DeviceEventsCollect(session, sn, 0).add(msg)


@fs_router.subscriber(q_ack)
async def ack(
    session: Session_dep,
    corr_id: Corr_id_dep,
):
    log.info("Subscribe ack queue")
    await DeviceTasksService(session, 0).pending(corr_id)


@fs_router.subscriber(q_req)
async def req(
    msg: RabbitMessage,
    session: Session_dep,
    sn: Sn_dep,
    corr_id: Corr_id_dep,
):
    log.info("Subscribe req queue")
    await DeviceTasksService(session, 0).select(sn, corr_id, msg)


@fs_router.subscriber(q_result)
async def result(
    msg: RabbitMessage,
    session: Session_dep,
    sn: Sn_dep,
    corr_id: Corr_id_dep,
):
    log.info("Subscribe res queue")
    await DeviceTasksService(session, 0).save(msg, sn, corr_id)


# Логируем количество подписчиков
try:
    count = len(getattr(fs_router, "_subscribers", []))
    log.info(f"✅ Subscribers registered: {count} handlers")
except Exception as e:
    log.error(f"Could not log subscribers count: {e}")

del sys
