from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.crud.device_repo import DeviceRepo
from core.logging_config import setup_module_logger
from core.schemas.devices import DeviceConnectStatus, DeviceTagPut
from core.services.rmq_admin import RmqAdmin

log = setup_module_logger(__name__, "srv_devices.log")


class DeviceService:
    @classmethod
    async def get_list(cls, session: AsyncSession, org_id, device_id: int | None):
        return await DeviceRepo.get(session, org_id, device_id)

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
                details=d,
            )
            for d in dev_online
        ]
        log.info("service DeviceService: update device connections %s", dev_statuses)
        await DeviceRepo.reset_connection_flag(session, list_devices)
        await DeviceRepo.update_connections(session, dev_statuses)

    @classmethod
    async def proxy_upsert_tag(
        cls, session, org_id, device_id, tag_value: DeviceTagPut
    ):
        if tag_value.tag.isascii():
            if len(tag_value.value) > 0:
                try:
                    tag_id = await DeviceRepo.upsert_tag(
                        session, org_id, device_id, tag_value.tag, tag_value.value
                    )
                except:
                    raise HTTPException(
                        status_code=404, detail="Tag/device_id uniqes error."
                    )
            else:
                raise HTTPException(status_code=404, detail="Value is empty")
        else:
            raise HTTPException(status_code=404, detail="Tag is not ascii")
        return tag_id
