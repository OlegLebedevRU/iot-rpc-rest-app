import json
import logging
from faststream.rabbit.fastapi import RabbitMessage
from core.crud.device_repo import DeviceRepo
from core.fs_broker import fs_router
from core.logging_config import setup_module_logger, log_rpc_debug
from core.services.device_events_collect import DeviceEventsCollect
from core.services.billing_publish import publish_billing_event
from core.services.billing_utils import evt_billing_counter_type, publish_then_process
from core.topologys.declare import (
    q_ack,
    q_req,
    q_evt,
    q_result,
    q_out,
    q_app,
    q_svc,
    q_device_conn_events,
)
from core.topologys.fs_depends import Session_dep, Sn_dep, Corr_id_dep
from core.diagnostics.mqtt_bridge import handle_device_output_message

from core.services.devices import DeviceService
from core.services.device_tasks import DeviceTasksService

log = setup_module_logger(__name__, "topology_queues.log")

# Отключаем логи от FastStream вида "Received", "Processed"
logging.getLogger("logger_proxy").setLevel(logging.WARNING)


# === Защита от повторной регистрации ===
_SUBSCRIBERS_REGISTERED = globals().get("_SUBSCRIBERS_REGISTERED", False)


def _ensure_single_registration():
    global _SUBSCRIBERS_REGISTERED
    if _SUBSCRIBERS_REGISTERED:
        log.warning("Subscribers already registered. Skipping duplicate subscription.")
        return False
    _SUBSCRIBERS_REGISTERED = True
    return True


async def _publish_billing_for_sn(
    session,
    sn,
    counter_type: str,
    payload_bytes: int = 0,
):
    try:
        dev_id = await DeviceRepo.get_device_id(session=session, sn=sn)
        if dev_id is None:
            return
        org_id = await DeviceRepo.get_org_id_by_device_id(session, device_id=dev_id)
        if org_id is None:
            return
        await publish_billing_event(
            org_id=org_id,
            device_id=dev_id,
            counter_type=counter_type,
            payload_bytes=payload_bytes,
        )
    except Exception as e:
        log.debug("Billing %s publish error (non-critical): %r", counter_type, e)


_REGISTER_SUBSCRIBERS = _ensure_single_registration()


if _REGISTER_SUBSCRIBERS:
    # === Регистрация подписчиков ===
    @fs_router.subscriber(q_evt)
    async def add_one_event(
        msg: RabbitMessage,
        session: Session_dep,
        sn: Sn_dep,
        corr_id: Corr_id_dep,
    ):
        # log.info("Subscribe event queue")
        from core import settings

        msg_headers = getattr(msg, "headers", {}) or {}
        try:
            event_type_code = int(msg_headers.get("event_type_code", 0))
        except TypeError, ValueError:
            log.debug(
                "Invalid EVT event_type_code header for billing (expected int): sn=%s raw_value=%s",
                sn,
                msg_headers.get("event_type_code"),
            )
            event_type_code = 0
        billing_counter_type = evt_billing_counter_type(
            event_type_code, settings.webhook.gauge_event_types
        )
        await publish_then_process(
            lambda: _publish_billing_for_sn(session, sn, billing_counter_type),
            lambda: DeviceEventsCollect(session, sn, 0).add(msg, corr_id=corr_id),
        )

    @fs_router.subscriber(q_ack)
    async def ack(
        session: Session_dep,
        sn: Sn_dep,
        corr_id: Corr_id_dep,
    ):
        # log.info("Subscribe ack queue")
        log_rpc_debug(sn, "rpc.ack.received", corr_id=corr_id)
        await publish_then_process(
            lambda: _publish_billing_for_sn(session, sn, "activity"),
            lambda: DeviceTasksService(session, 0).pending(corr_id, sn),
        )

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
        await publish_then_process(
            lambda: _publish_billing_for_sn(session, sn, "activity"),
            lambda: DeviceTasksService(session, 0).select(sn, corr_id, msg),
        )

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
        payload_bytes = len(msg.body) if msg.body else 0
        saved = await DeviceTasksService(session, 0).save(msg, sn, corr_id)
        if saved:
            await _publish_billing_for_sn(
                session, sn, "res", payload_bytes=payload_bytes
            )

    @fs_router.subscriber(q_out)
    async def diagnostics_output(
        msg: RabbitMessage,
        sn: Sn_dep,
    ):
        routing_key = getattr(msg, "routing_key", None) or f"dev.{sn}.out"
        await handle_device_output_message(routing_key=routing_key, payload=msg.body)

    @fs_router.subscriber(q_app)
    async def app_connect_handler(
        msg: RabbitMessage,
        session: Session_dep,
        sn: Sn_dep,
    ):
        try:
            body = (
                (msg.body or b"").decode("utf-8", errors="replace").strip().strip('"')
            )
        except Exception as e:
            log.warning("Failed to decode app connect message for %s: %s", sn, e)
            return

        if body == "app_online":
            value = True
        elif body == "app_offline":
            value = False
        else:
            log.warning("Unknown app connect message payload for %s: %s", sn, body)
            return

        await DeviceRepo.update_connect_flag(session, sn, "app_connect", value)
        await session.commit()

    @fs_router.subscriber(q_svc)
    async def svc_connect_handler(
        msg: RabbitMessage,
        session: Session_dep,
        sn: Sn_dep,
    ):
        try:
            body = (
                (msg.body or b"").decode("utf-8", errors="replace").strip().strip('"')
            )
        except Exception as e:
            log.warning("Failed to decode svc connect message for %s: %s", sn, e)
            return

        if body == "svc_online":
            value = True
        elif body == "svc_offline":
            value = False
        else:
            log.warning("Unknown svc connect message payload for %s: %s", sn, body)
            return

        await DeviceRepo.update_connect_flag(session, sn, "svc_connect", value)
        await session.commit()

    @fs_router.subscriber(q_device_conn_events)
    async def device_connection_events_handler(
        msg: RabbitMessage,
        session: Session_dep,
    ):
        routing_key = (
            getattr(msg, "routing_key", "")
            or getattr(getattr(msg, "raw_message", None), "routing_key", "")
            or ""
        )
        headers = (
            getattr(msg, "headers", None)
            or getattr(getattr(msg, "raw_message", None), "headers", None)
            or {}
        )
        try:
            payload = json.loads((msg.body or b"{}").decode("utf-8", errors="replace"))
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}

        await DeviceService.handle_connection_event(
            session=session,
            routing_key=routing_key,
            payload=payload,
            headers=headers,
        )


# Логируем количество подписчиков
try:
    count = len(getattr(fs_router.broker, "_subscribers", []))
    log.info(f"✅ Subscribers registered: {count} handlers")
except Exception as e:
    log.error(f"Could not log subscribers count: {e}")
