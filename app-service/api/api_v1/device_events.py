from core.logging_config import setup_module_logger
from typing import Annotated, List
from fastapi import APIRouter
from fastapi.params import Query
from fastapi_pagination import Page
from api.api_v1.api_depends import Session_dep, Org_dep
from core import settings
from core.schemas.device_events import (
    DevEventOut,
    DevEventFields,
    DevEventFieldsRequest,
)
from core.services.device_events import DeviceEventsService

log = setup_module_logger(__name__, "api_dev_events.log")
router = APIRouter(
    prefix=settings.api.v1.device_events,
    tags=["Device events"],
)


@router.get(
    "/",
    description="Events search by device_id with pagination",
    response_model=Page[DevEventOut],
)
async def list_device_events(
    device_id: Annotated[int, Query()],
    session: Session_dep,
    org_id: Org_dep,
    events_include: Annotated[list[int] | None, Query()] = None,
    events_exclude: Annotated[list[int] | None, Query()] = None,
) -> Page[DevEventOut] | None:
    return await DeviceEventsService(session, None, org_id).list(
        device_id, events_include, events_exclude
    )


# Пример ответа для /incremental
EXAMPLE_INCREMENTAL_RESPONSE = [
    {
        "id": 1095037,
        "device_id": 4619,
        "event_type_code": 3,
        "dev_event_id": 48846,
        "created_at": "2026-03-11T17:50:37.458000Z",
        "dev_timestamp": "2026-03-11T17:50:37Z",
        "payload": {
            "101": 48847,
            "102": "2026-03-11T20:50:37ZMSK",
            "200": 3,
            "300": [{"301": "044AFE42C76781", "302": 6, "303": 0}],
        },
    },
    {
        "id": 1095038,
        "device_id": 4619,
        "event_type_code": 44,
        "dev_event_id": 48848,
        "created_at": "2026-03-11T17:50:54.950000Z",
        "dev_timestamp": "2026-03-11T17:50:54Z",
        "payload": {
            "101": 48848,
            "102": "2026-03-11T20:50:54ZMSK",
            "200": 44,
            "300": [
                {
                    "310": "leo4_gateway_v_1.1",
                    "311": 0,
                    "312": 0,
                    "313": 4239604,
                    "314": "d4:e9:f4:e4:cb:4b",
                    "323": "192.168.1.179",
                    "324": "a2b0004619c16072d240126",
                    "325": "192.168.1.179",
                    "336": 0,
                    "338": 0,
                }
            ],
        },
    },
]


@router.get(
    "/incremental",
    description="Get incremental events. If last_event_id is not provided, uses stored offset per device.",
    response_model=List[DevEventOut],
    responses={
        200: {
            "description": "Список новых событий, начиная с последнего ID",
            "content": {"application/json": {"example": EXAMPLE_INCREMENTAL_RESPONSE}},
        }
    },
)
async def get_incremental_events(
    session: Session_dep,
    org_id: Org_dep,
    device_id: Annotated[int | None, Query()] = None,
    last_event_id: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> List[DevEventOut]:
    """
    Get incremental events. If last_event_id is not provided, uses stored offset per device.
    Получение строго инкрементального списка событий.
    - **device_id**: ID устройства, если нет - выдача по всем.
    - **last_event_id**: последний (запомненный у клиента) ID события, если нет -
    выдача последних событий по версии сервера.
    - **limit**: ограничение выдачи (0-100), по умолчанию 50.
    Проверяется принадлежность постамата к организации (если указан org_id).
    Возвращает объект задачи (TaskResponse).
    """

    return await DeviceEventsService(
        session, None, org_id=org_id
    ).get_incremental_events(device_id, last_event_id, limit)


@router.get(
    "/fields/",
    description="Fields select from events",
    response_model=List[DevEventFields],
)
async def get_event_fields(
    session: Session_dep,
    org_id: Org_dep,
    request: Annotated[DevEventFieldsRequest, Query()],
) -> List[DevEventFields]:
    return await DeviceEventsService(session, None, org_id).fields(
        request.device_id,
        request.event_type_code,
        request.tag,
        request.interval_m,
        request.limit,
    )
