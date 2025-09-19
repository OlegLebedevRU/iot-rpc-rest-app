import logging

from core.fs_broker import fs_router
from core.services.device_tasks import DeviceTasksService
from core.services.rmq_admin import RmqAdmin
from core.topologys import Session_dep, q_jobs

log = logging.getLogger(__name__)


@fs_router.subscriber(q_jobs)
async def jobs_parse(session: Session_dep):
    await DeviceTasksService(session, 0).ttl(decrement=1)
    devices = await RmqAdmin.get_online_devices(
        sn_arr=[
            "a1b0004617c24558d080925",
            "a3b0000000c10221d290825",
        ]
    )
    for device in devices:
        log.info("get api: %s", device)
