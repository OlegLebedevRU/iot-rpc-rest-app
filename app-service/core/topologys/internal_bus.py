import logging.handlers

from core import settings
from core.fs_broker import fs_router
from core.schemas.rmq_admin import RmqClientsAction
from core.services.device_tasks import DeviceTasksService
from core.services.devices import DeviceService
from core.services.rmq_admin import RmqAdmin
from core.topologys.fs_depends import Session_dep
from core.topologys import q_jobs, rmq_api_client_action

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
