import logging
from fastapi import (
    APIRouter,
)
from fastapi_pagination import Page
from pydantic import UUID4
from api.api_v1.api_depends import Session_dep, Org_dep
from core import settings
from core.schemas.device_tasks import (
    TaskCreate,
    TaskResponse,
    TaskResponseResult,
    TaskResponseDeleted,
    TaskListOut,
)
from core.services.device_tasks import DeviceTasksService

log = logging.getLogger(__name__)
router = APIRouter(
    prefix=settings.api.v1.device_tasks,
    tags=["Device tasks"],
)


@router.post("/", response_model=TaskResponse)
async def touch_task(
    session: Session_dep,
    task_create: TaskCreate,
    org_id: Org_dep,
):
    return await DeviceTasksService(session, org_id).create(task_create)


@router.get("/{id}", response_model=TaskResponseResult)
async def get_task(
    id: UUID4,
    session: Session_dep,
    org_id: Org_dep,
) -> TaskResponseResult:
    return await DeviceTasksService(session, org_id).get(id)


@router.get(
    "/",
    response_model=Page[TaskListOut],
    description=f"Tasks search by device_id with pagination",
)
async def list_tasks(
    session: Session_dep,
    org_id: Org_dep,
    device_id: int | None = 0,
) -> Page[TaskListOut]:
    return await DeviceTasksService(session, org_id).list(device_id)


@router.delete("/{id}", response_model=TaskResponseDeleted, description="soft delete")
async def delete_task(
    id: UUID4,
    session: Session_dep,
    org_id: Org_dep,
) -> TaskResponseDeleted:
    return await DeviceTasksService(session, org_id).delete(id)
