import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.crud.device_repo import DeviceRepo
from core.models import DeviceConnection
from core.schemas.devices import DeviceConnectStatus
from core.services.rmq_admin import RmqAdmin

log = logging.getLogger(__name__)


class DeviceService:

    @classmethod
    async def get_connect_status_ids(cls, device_ids: [int]):
        pass

    @classmethod
    async def get_connect_status_sns(cls, sn_arr: [str]):
        pass

    @classmethod
    async def update_device_connections(cls, session: AsyncSession):
        # todo need iterable select - request
        list_devices = await DeviceRepo.list(session)
        dev_online = await RmqAdmin.get_online_devices(list_devices)
        dev_statuses: list[DeviceConnectStatus] = [
            DeviceConnectStatus(
                client_id=d.user,
                connected_at=d.connected_at,
                last_checked_result=True,
                device_id=0,
                details=d.model_dump_json(exclude="client_properties"),
            )
            for d in dev_online
        ]
        log.info("service DeviceService: update device connections %s", dev_statuses)
        await DeviceRepo.reset_connection_flag(session, list_devices)
        await DeviceRepo.update_connections(session, dev_statuses)
