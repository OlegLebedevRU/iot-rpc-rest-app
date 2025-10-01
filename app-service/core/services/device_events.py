import logging
import time
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from core.crud.dev_events_repo import EventRepository
from core.crud.device_repo import DeviceRepo
from core.schemas.device_events import DevEventBody

log = logging.getLogger(__name__)


class DeviceEventsService:
    def __init__(self, session, sn: str = None, org_id: int = 0):
        self.session: AsyncSession = session
        self.sn = sn
        self.org_id = org_id

    async def add(self, msg):
        try:
            dev_id = await DeviceRepo.get_device_id(session=self.session, sn=self.sn)
        except Exception as e:
            log.info(
                "Mqtt received EVENT: <dev.%s.evt>, error select device_id, error= =%s",
                self.sn,
                e,
            )
            return
        if dev_id is None:
            return
        if hasattr(msg, "headers"):
            msg_headers = msg.headers
            if "event_type_code" in msg_headers:
                event_type_code = int(msg_headers["event_type_code"])
            else:
                event_type_code = 0
            if "dev_event_id" in msg_headers:
                dev_event_id = int(msg.headers["dev_event_id"])
            else:
                dev_event_id = 0
            if "dev_timestamp" in msg_headers:
                dev_timestamp = msg.headers["dev_timestamp"]
            else:
                dev_timestamp = int(time.time())
            log.info(
                "Mqtt received EVENT: event_type_code =%d, dev_event_id=%d",
                event_type_code,
                dev_event_id,
            )
            event = DevEventBody(
                device_id=dev_id,
                event_type_code=event_type_code,
                dev_event_id=dev_event_id,
                dev_timestamp=dev_timestamp,
                payload=msg.body.decode(),
            )
            await EventRepository.add_event(self.session, event)

    async def list(self, device_id, events_exclude):
        events = await EventRepository.get_events_page(
            self.session, device_id, events_exclude=events_exclude
        )
        if events is None:
            raise HTTPException(status_code=404, detail="Events not found")
        return events
