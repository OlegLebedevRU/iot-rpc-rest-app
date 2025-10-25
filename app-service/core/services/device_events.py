import json
import logging.handlers
import time
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core import settings
from core.crud.dev_events_repo import EventRepository
from core.crud.device_repo import DeviceRepo
from core.schemas.device_events import DevEventBody, DevEventFields

log = logging.getLogger(__name__)
fh = logging.handlers.RotatingFileHandler(
    "/var/log/app/srv_dev_evnt.log",
    mode="a",
    maxBytes=10 * 1024 * 1024,
    backupCount=10,
    encoding=None,
)
fh.setLevel(logging.INFO)
formatter = logging.Formatter(settings.logging.log_format)
fh.setFormatter(formatter)
log.addHandler(fh)


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
            payload = msg.body.decode()
            event = DevEventBody(
                device_id=dev_id,
                event_type_code=event_type_code,
                dev_event_id=dev_event_id,
                dev_timestamp=dev_timestamp,
                payload=payload,
            )
            await EventRepository.add_event(self.session, event)
            if event_type_code == 44:
                await DeviceRepo.upsert_gauge(
                    self.session,
                    org_id=self.org_id,
                    device_id=dev_id,
                    type=str(event_type_code),
                    gauges=json.loads(payload),
                )

    async def list(self, device_id, events_include, events_exclude):
        events = await EventRepository.get_events_page(
            self.session,
            device_id,
            events_include=events_include,
            events_exclude=events_exclude,
        )
        if events is None:
            raise HTTPException(status_code=404, detail="Events not found")
        return events

    async def fields(self, device_id, event_type_code, tag, interval_m, limit):
        fields = await EventRepository.get_event_fields(
            self.session, device_id, event_type_code, tag, interval_m, limit
        )
        if fields is None:
            raise HTTPException(status_code=404, detail="Fields not found")
        fres: list[DevEventFields] = [
            DevEventFields(
                created_at=f.created_at,
                value=f.value if f.value is not None else "",
                interval_sec=f.interval_sec if f.interval_sec is not None else 0,
            )
            for f in fields
        ]

        return fres


# """"
# dev_statuses: list[DeviceConnectStatus] = [
#             DeviceConnectStatus(
#                 client_id=d.user,
#                 connected_at=d.connected_at,
#                 last_checked_result=True,
#                 device_id=0,
#                 details=d.model_dump_json(exclude="client_properties"),
#             )
#             for d in dev_online
#         ]
# """


# """
# async def get_event_fields(
#         cls,
#         session: AsyncSession,
#         device_id: int,
#         event_type_code: int,
#         tag: int,
#         interval_m: int | None,
#         limit: int | None = 10,
#     ):
# """
