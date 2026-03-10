import json
import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from core import settings
from core.crud.dev_events_repo import EventRepository
from core.crud.device_repo import DeviceRepo
from core.logging_config import setup_module_logger

from core.schemas.device_events import DevEventBody
from core.topologys.declare import topic_publisher, direct_exchange

log = setup_module_logger(__name__, "srv_dev_evnt_collect.log")

logging.getLogger("logger_proxy").setLevel(logging.WARNING)


class DeviceEventsCollect:
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
                dev_event_id = int(msg_headers["dev_event_id"])
            else:
                dev_event_id = 0
            if "dev_timestamp" in msg_headers:
                dev_timestamp = msg.headers["dev_timestamp"]
            else:
                dev_timestamp = int(time.time())
            if event_type_code != 44:
                log.info(
                    "Mqtt received EVENT: event_type_code =%d, dev_event_id=%d",
                    event_type_code,
                    dev_event_id,
                )
            try:
                payload_dict = json.loads(msg.body.decode())
            except ValueError, TypeError:
                payload_dict = {}
            event = DevEventBody(
                device_id=dev_id,
                event_type_code=event_type_code,
                dev_event_id=dev_event_id,
                dev_timestamp=dev_timestamp,
                payload=payload_dict,
            )
            await EventRepository.add_event(self.session, event)
            if event_type_code == 44:
                await DeviceRepo.upsert_gauge(
                    self.session,
                    org_id=self.org_id,
                    device_id=dev_id,
                    type=str(event_type_code),
                    gauges=payload_dict,
                )
            else:
                await topic_publisher.publish(
                    routing_key=settings.webhook.webhooks_queue,
                    message=msg.body,
                    exchange=direct_exchange,
                    expiration=10 * 60_000,
                    headers={
                        "x-device-id": str(dev_id),
                        "x-msg-type": "msg-event",
                    },
                )
