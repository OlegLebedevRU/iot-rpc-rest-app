import logging
import sys
from faststream.rabbit.fastapi import RabbitMessage
from core.fs_broker import fs_router
from core.logging_config import (
    setup_module_logger,
    log_rpc_debug,
    build_rabbit_message_debug_snapshot,
    RPC_REQ_VERBOSE_DEBUG_SNS,
)
from core.services.device_events_collect import DeviceEventsCollect
from core.topologys.declare import q_ack, q_req, q_evt, q_result
from core.topologys.fs_depends import Session_dep, Sn_dep, Corr_id_dep

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
    # log.info("Subscribe event queue")
    await DeviceEventsCollect(session, sn, 0).add(msg)


@fs_router.subscriber(q_ack)
async def ack(
    session: Session_dep,
    sn: Sn_dep,
    corr_id: Corr_id_dep,
):
    # log.info("Subscribe ack queue")
    log_rpc_debug(sn, "rpc.ack.received", corr_id=corr_id)
    await DeviceTasksService(session, 0).pending(corr_id, sn)


@fs_router.subscriber(q_req)
async def req(
    msg: RabbitMessage,
    session: Session_dep,
    sn: Sn_dep,
    corr_id: Corr_id_dep,
):
    # log.info("Subscribe req queue")
    headers = getattr(msg, "headers", None) or {}
    log_rpc_debug(
        sn,
        "rpc.req.received",
        corr_id=corr_id,
        slave_ws=headers.get("slave_ws"),
    )
    if sn in RPC_REQ_VERBOSE_DEBUG_SNS:
        log_rpc_debug(
            sn,
            "rpc.req.debug_dump",
            extracted_corr_id=corr_id,
            snapshot=build_rabbit_message_debug_snapshot(msg),
        )
    await DeviceTasksService(session, 0).select(sn, corr_id, msg)


@fs_router.subscriber(q_result)
async def result(
    msg: RabbitMessage,
    session: Session_dep,
    sn: Sn_dep,
    corr_id: Corr_id_dep,
):
    log.info("Processing message from the results queue sn = %s", sn)
    headers = getattr(msg, "headers", None) or {}
    log_rpc_debug(
        sn,
        "rpc.res.received",
        corr_id=corr_id,
        ext_id=headers.get("ext_id"),
        status_code=headers.get("status_code"),
    )
    await DeviceTasksService(session, 0).save(msg, sn, corr_id)


# Логируем количество подписчиков
try:
    count = len(getattr(fs_router, "_subscribers", []))
    log.info(f"✅ Subscribers registered: {count} handlers")
except Exception as e:
    log.error(f"Could not log subscribers count: {e}")

del sys
