import json
import logging
import time
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core import settings
from core.crud.dev_events_repo import EventRepository
from core.crud.device_repo import DeviceRepo
from core.logging_config import setup_module_logger, log_rpc_debug

from core.schemas.device_events import DevEventBody
from core.services.device_task_processing import send_eva
from core.topologys.declare import topic_publisher, direct_exchange

log = setup_module_logger(__name__, "srv_dev_evnt_collect.log")

logging.getLogger("logger_proxy").setLevel(logging.WARNING)


class DeviceEventsCollect:
    def __init__(self, session, sn: str = None, org_id: int = 0):
        self.session: AsyncSession = session
        self.sn = sn
        self.org_id = org_id

    def _needs_eva(self, event_type_code: int | None, dev_event_id: int | None) -> bool:
        """
        EVA отправляется только когда:
        - event_type_code задан и != 0, и не является gauge-типом
        - dev_event_id задан и != 0
        """
        if event_type_code is None or event_type_code == 0:
            return False
        if event_type_code in settings.webhook.gauge_event_types:
            return False
        if dev_event_id is None or dev_event_id == 0:
            return False
        return True

    async def add(self, msg, corr_id: UUID | str | None = None):
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

        msg_headers = getattr(msg, "headers", {})
        event_type_code = int(msg_headers.get("event_type_code", 0))
        dev_event_id = int(msg_headers.get("dev_event_id", 0))
        dev_timestamp = int(msg_headers.get("dev_timestamp", time.time()))

        # Проверяем, является ли событие "gauge"-типом
        is_gauge_event = event_type_code in settings.webhook.gauge_event_types

        # Проверяем, нужно ли отправлять EVA
        needs_eva = self._needs_eva(event_type_code, dev_event_id)

        try:
            payload_dict = json.loads(msg.body.decode()) if msg.body else {}
        except (ValueError, TypeError):
            payload_dict = {}

        if not is_gauge_event:
            log.info(
                "Mqtt received EVENT: <dev.%s.evt>, event_type_code =%d, dev_event_id=%d",
                self.sn,
                event_type_code,
                dev_event_id,
            )

        if is_gauge_event:
            # Только обновляем gauge, без создания события и публикации вебхука
            await DeviceRepo.upsert_gauge(
                self.session,
                org_id=self.org_id,
                device_id=dev_id,
                type=str(event_type_code),
                gauges=payload_dict,
            )
        else:
            # Только здесь нужно создавать DevEventBody
            event = DevEventBody(
                device_id=dev_id,
                event_type_code=event_type_code,
                dev_event_id=dev_event_id,
                dev_timestamp=dev_timestamp,
                payload=payload_dict,
            )
            try:
                is_new = await EventRepository.add_event(self.session, event)
            except Exception as e:
                log.error(
                    "EVT processing error: <dev.%s.evt>, dev_event_id=%d, error=%s",
                    self.sn,
                    dev_event_id,
                    e,
                )
                if needs_eva:
                    await send_eva(
                        sn=self.sn,
                        event_type_code=event_type_code,
                        dev_event_id=dev_event_id,
                        corr_id=corr_id,
                        status="error",
                    )
                return

            # Публикуем вебхук только для новых событий
            if is_new:
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

            # EVA отправляется и для новых, и для дубликатов (идемпотентность)
            if needs_eva:
                await send_eva(
                    sn=self.sn,
                    event_type_code=event_type_code,
                    dev_event_id=dev_event_id,
                    corr_id=corr_id,
                    status="success",
                )

