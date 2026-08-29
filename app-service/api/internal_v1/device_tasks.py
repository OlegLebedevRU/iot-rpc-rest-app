from fastapi import APIRouter
from fastapi_pagination import Page
from pydantic import UUID4

from api.internal_v1.internal_depends import Internal_Org_dep, Session_dep
from core import settings
from core.logging_config import setup_module_logger
from core.schemas.device_tasks import (
    TaskCreate,
    TaskResponse,
    TaskResponseResult,
    TaskResponseDeleted,
    TaskListOut,
)
from core.services.device_tasks import DeviceTasksService

log = setup_module_logger(__name__, "api_internal_device_tasks.log")
router = APIRouter(
    prefix=settings.api.internal_v1.device_tasks,
    tags=["Internal Device Tasks"],
    include_in_schema=False,
)


@router.post("/", response_model=TaskResponse)
async def touch_task(
    session: Session_dep,
    task_create: TaskCreate,
    org_id: Internal_Org_dep,
) -> TaskResponse:
    return await DeviceTasksService(session, org_id).create(task_create)


@router.get("/{id}", response_model=TaskResponseResult)
async def get_task(
    id: UUID4,
    session: Session_dep,
    org_id: Internal_Org_dep,
) -> TaskResponseResult:
    return await DeviceTasksService(session, org_id).get(id)


@router.get(
    "/",
    response_model=Page[TaskListOut],
    description="Tasks search by device_id with pagination",
)
async def list_tasks(
    session: Session_dep,
    org_id: Internal_Org_dep,
    device_id: int,
) -> Page[TaskListOut]:
    return await DeviceTasksService(session, org_id).list(device_id)


@router.delete("/{id}", response_model=TaskResponseDeleted, description="soft delete")
async def delete_task(
    id: UUID4,
    session: Session_dep,
    org_id: Internal_Org_dep,
) -> TaskResponseDeleted:
    return await DeviceTasksService(session, org_id).delete(id)
