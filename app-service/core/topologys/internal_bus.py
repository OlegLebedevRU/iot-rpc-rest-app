import json
import logging.handlers

from faststream.rabbit.fastapi import RabbitMessage

from core import settings
from core.crud.device_repo import DeviceRepo
from core.fs_broker import fs_router
from core.integrations.webhooks import Webhook
from core.schemas.rmq_admin import RmqClientsAction
from core.services.device_tasks import DeviceTasksService
from core.services.devices import DeviceService
from core.services.rmq_admin import RmqAdmin
from core.topologys.fs_depends import Session_dep
from core.topologys import q_jobs, rmq_api_client_action, webhook_action

log = logging.getLogger(__name__)
fh = logging.handlers.RotatingFileHandler(
    "/var/log/app/internal_queues.log",
    mode="a",
    maxBytes=10 * 1024 * 1024,
    backupCount=10,
    encoding=None,
)
fh.setLevel(logging.INFO)
formatter = logging.Formatter(settings.logging.log_format)
fh.setFormatter(formatter)
log.addHandler(fh)


@fs_router.subscriber(q_jobs)
async def jobs_parse(session: Session_dep):
    await DeviceTasksService(session, 0).ttl(decrement=1)


@fs_router.subscriber(rmq_api_client_action)
async def rmq_api_client(session: Session_dep, api_action: RmqClientsAction):
    #
    if api_action.action == "get_online_status":
        #
        devices = await RmqAdmin.get_online_devices(sn_arr=api_action.clients)
        for device in devices:
            log.info("RmqAdmin.get_online_devices: %s", device)
    #
    elif api_action.action == "update_online_status":
        #
        await DeviceService.update_device_connections(session)
        log.info("Subscribed job = Updated device connection status")


@fs_router.subscriber(webhook_action)
async def webhooks(session: Session_dep, msg: RabbitMessage):
    # log.info("Webhook = %s", str(msg))
    if "x-msg-type" not in msg.raw_message.headers:
        return
    if msg.headers["x-msg-type"] == "msg-event":
        if "x-device-id" in msg.raw_message.headers:
            device_id = int((msg.raw_message.headers["x-device-id"]).encode())
            try:
                payload = json.loads(msg.body.decode())
            except ValueError or TypeError:
                payload = {}
            # payload = json.loads(msg.body.decode())
            # device_id = int(msg.raw_message.routing_key.split(".")[1])
            org_id = await DeviceRepo.get_org_id_by_device_id(
                session, device_id=device_id
            )
            if org_id is not None:
                log.info("event webhook(org_id):(%d) %s", org_id, payload)
                # todo get url by org_id
                async with Webhook(
                    url="https://d5dgp292c4okr1knd17q.g3ab4gln.apigw.yandexcloud.net",
                    path_suffix="/event/" + str(device_id),
                    headers={"x-msg-type": "msg-event"},
                ) as wh:
                    await wh.send(payload)
    elif msg.headers["x-msg-type"] == "msg-task-result":
        # headers = (
        #     {
        #         "x-device-id": str(dev_id),
        #         "x-msg-type": "msg-task-result",
        #         "x-ext-id": str(ext_id),
        #         "x-result-id": str(result_id),
        #     },
        # )
        if "x-device-id" in msg.raw_message.headers:
            device_id = int((msg.raw_message.headers["x-device-id"]).encode())
            # payload = json.loads(msg.body.decode())
            try:
                payload = json.loads(msg.body.decode())
            except ValueError or TypeError:
                payload = {}
            org_id = await DeviceRepo.get_org_id_by_device_id(
                session, device_id=device_id
            )
            if org_id is not None:
                log.info("task-result webhook(org_id):(%d) %s", org_id, payload)
                # todo get url by org_id
                headers = {"x-msg-type": "msg-task-result"}
                if msg.headers["x-ext-id"]:
                    headers["x-ext-id"] = msg.headers["x-ext-id"]
                if msg.headers["x-result-id"]:
                    headers["x-result-id"] = msg.headers["x-result-id"]
                headers["x-device-id"] = str(device_id)
                async with Webhook(
                    url="https://d5dgp292c4okr1knd17q.g3ab4gln.apigw.yandexcloud.net",
                    path_suffix="/task-result/" + msg.correlation_id,
                    headers=headers,
                ) as wh:
                    await wh.send(payload)
    else:
        return
