import logging
from typing import Annotated
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Header,
)
from fastapi_pagination import Page
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession
from core import settings
from core.config import RoutingKey
from core.crud.dev_tasks_repo import TasksRepository
from core.crud.device_repo import DeviceRepo
from core.models import db_helper
from core.models.orgs import Org
from core.schemas.device_tasks import (
    TaskCreate,
    TaskResponse,
    TaskResponseResult,
    TaskResponseDeleted,
    TaskNotify,
    TaskListOut,
)
from core.services.device_tasks import DeviceTasksService

log = logging.getLogger(__name__)
router = APIRouter(
    prefix=settings.api.v1.device_tasks,
    tags=["Device tasks"],
)


async def org_id_dep(
    org_id: Annotated[int, Header()],
):
    return org_id


@router.post("/", response_model=TaskResponse)
async def touch_task(
    session: Annotated[
        AsyncSession,
        Depends(db_helper.session_getter),
    ],
    task_create: TaskCreate,
    org_id: Annotated[int, Depends(org_id_dep)],
):
    task_service = DeviceTasksService(session, org_id)
    return await task_service.create_task(task_create)


@router.get("/{id}", response_model=TaskResponseResult)
async def get_task(
    id: UUID4,
    session: Annotated[
        AsyncSession,
        Depends(db_helper.session_getter),
    ],
    org_id: Annotated[int | None, Header()] = None,
) -> TaskResponseResult:
    task_service = DeviceTasksService(session, org_id)
    return await task_service.get(id)


@router.get(
    "/",
    response_model=Page[TaskListOut],
    description=f"Tasks search by device_id with pagination",
)
async def list_tasks(
    session: Annotated[AsyncSession, Depends(db_helper.session_getter)],
    device_id: int | None = 0,
    org_id: Annotated[int | None, Header()] = None,
) -> Page[TaskListOut]:
    tasks: Page[TaskListOut] = await TasksRepository.get_tasks(
        session, device_id, org_id
    )
    if tasks is None:
        raise HTTPException(status_code=404, detail="Tasks not found")
    return tasks


@router.delete("/{id}", response_model=TaskResponseDeleted, description="soft delete")
async def delete_task(
    id: UUID4,
    session: Annotated[
        AsyncSession,
        Depends(db_helper.session_getter),
    ],
    org_id: Annotated[int | None, Header()] = None,
) -> TaskResponseDeleted:  # TaskResponseStatus:
    task: TaskResponseDeleted = await TasksRepository.delete_task(session, id, org_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
