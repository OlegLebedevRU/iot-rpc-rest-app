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

# Примеры ответа
from core.examples import (
    EXAMPLE_PAGINATED_RESPONSE,
    EXAMPLE_INCREMENTAL_RESPONSE,
    EXAMPLE_FIELDS_RESPONSE,
)


@router.get(
    "/",
    description="Events search by device_id with pagination",
    response_model=Page[DevEventOut],
    responses={
        200: {
            "description": "Список событий с пагинацией",
            "content": {"application/json": {"example": EXAMPLE_PAGINATED_RESPONSE}},
        }
    },
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
    description="""
Fields select from events.

Can be used in polling mode to confirm a specific event by tag value, for example
`CellOpenEvent` with `event_type_code=13` and `tag=304`.

Example:
```bash
curl -X 'GET' \\
  'https://dev.leo4.ru/api/v1/device-events/fields/?device_id=4617&event_type_code=13&tag=304&interval_m=5&limit=10' \\
  -H 'accept: application/json' \\
  -H 'x-api-key: ApiKey <key>'
```
""",
    response_model=List[DevEventFields],
    responses={
        200: {
            "description": "Список значений поля из событий за интервал; подходит для polling по event_type_code и tag",
            "content": {"application/json": {"example": EXAMPLE_FIELDS_RESPONSE}},
        }
    },
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
