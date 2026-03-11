import json
import logging
from core.logging_config import setup_module_logger
from faststream.rabbit.fastapi import RabbitMessage
from core.crud.device_repo import DeviceRepo
from core.crud.webhook_repo import WebhookRepo
from core.fs_broker import fs_router
from core.integrations.webhooks import Webhook
from core.schemas.rmq_admin import RmqClientsAction
from core.services.devices import DeviceService
from core.services.rmq_admin import RmqAdmin
from core.topologys.fs_depends import Session_dep
from core.topologys.declare import q_jobs, rmq_api_client_action, webhook_action

# Отключаем лишние логи от FastStream
logging.getLogger("logger_proxy").setLevel(logging.WARNING)

log = setup_module_logger(__name__, "internal_bus.log")


@fs_router.subscriber(q_jobs)
async def jobs_parse(session: Session_dep):
    from core.services.device_tasks import DeviceTasksService

    await DeviceTasksService(session, 0).ttl(decrement=1)


@fs_router.subscriber(rmq_api_client_action)
async def rmq_api_client(session: Session_dep, api_action: RmqClientsAction):
    if api_action.action == "get_online_status":
        devices = await RmqAdmin.get_online_devices(sn_arr=api_action.clients)
        for device in devices:
            log.info("RmqAdmin.get_online_devices: %s", device)
    elif api_action.action == "update_online_status":
        await DeviceService.update_device_connections(session)
        log.info("Subscribed job = Updated device connection status")


@fs_router.subscriber(webhook_action)
async def webhooks(session: Session_dep, msg: RabbitMessage):
    if "x-msg-type" not in msg.raw_message.headers:
        return

    msg_type = msg.headers["x-msg-type"]
    device_id_str = msg.raw_message.headers.get("x-device-id")
    if not device_id_str:
        return

    try:
        device_id = int(device_id_str)
    except ValueError, TypeError:
        log.warning("Invalid device_id in headers: %s", device_id_str)
        return

    # Получаем org_id
    org_id = await DeviceRepo.get_org_id_by_device_id(session, device_id=device_id)
    if org_id is None:
        log.info("No org_id found for device_id=%d", device_id)
        return

    # Получаем вебхук
    webhook_repo = WebhookRepo(session)
    webhook_obj = await webhook_repo.get_by_org_and_type(org_id, msg_type)
    if not webhook_obj or not webhook_obj.is_active:
        log.info("No active webhook for org_id=%d, event_type=%s", org_id, msg_type)
        return

    # Парсим тело
    try:
        payload = json.loads(msg.body.decode())
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        log.error("Failed to decode message body: %s", str(e))
        payload = {}

    # Формируем заголовки
    headers = dict(webhook_obj.headers or {})
    headers["x-msg-type"] = msg_type
    headers["x-device-id"] = str(device_id)

    if msg_type == "msg-task-result":
        if msg.headers.get("x-ext-id"):
            headers["x-ext-id"] = msg.headers["x-ext-id"]
        if msg.headers.get("x-result-id"):
            headers["x-result-id"] = msg.headers["x-result-id"]

    # Отправляем
    path_suffix = (
        f"/{device_id}" if msg_type == "msg-event" else f"/{msg.correlation_id}"
    )
    async with Webhook(
        url=str(webhook_obj.url),
        path_suffix=path_suffix,
        headers=headers,
    ) as wh:
        await wh.send(payload)

    log.info(
        "Webhook sent to org_id=%d, url=%s, type=%s", org_id, webhook_obj.url, msg_type
    )
