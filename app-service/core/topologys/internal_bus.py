import logging

from core.fs_broker import fs_router
from core.schemas.rmq_admin import RmqClientsAction
from core.services.device_tasks import DeviceTasksService
from core.services.rmq_admin import RmqAdmin
from core.topologys.fs_depends import Session_dep
from core.topologys import q_jobs, rmq_api_client_action

log = logging.getLogger(__name__)


@fs_router.subscriber(q_jobs)
async def jobs_parse(session: Session_dep):
    await DeviceTasksService(session, 0).ttl(decrement=1)


@fs_router.subscriber(rmq_api_client_action)
async def rmq_api_client_action(session: Session_dep, api_action: RmqClientsAction):
    # sn_arr = api_action.clients
    if api_action.action == "get_online_status":
        devices = await RmqAdmin.get_online_devices(sn_arr=api_action.clients)
        for device in devices:
            log.info("RmqAdmin.get_online_devices: %s", device)
