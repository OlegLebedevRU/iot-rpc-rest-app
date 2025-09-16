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
from core.topologys.fs_queues import topic_publisher


log = logging.getLogger(__name__)
router = APIRouter(
    prefix=settings.api.v1.device_tasks,
    tags=["Device tasks"],
)


@router.post("/", response_model=TaskResponse)
async def create_task(
    session: Annotated[
        AsyncSession,
        Depends(db_helper.session_getter),
    ],
    task_create: TaskCreate,
    org_id: Annotated[int | None, Header()] = None,
):
    sn = await DeviceRepo.get_device_sn(session, task_create.device_id, org_id)
    if sn is None:
        log.info(
            "trying to create task failed - device_id not found = %d",
            task_create.device_id,
        )
        raise HTTPException(status_code=404, detail="device_id not found")
    task = await TasksRepository.create_task(
        session=session,
        task=task_create,
    )
    log.info("Created task %s", task)
    rk = RoutingKey(settings.rmq.prefix_srv, sn, settings.rmq.suffix_task)
    notify: TaskNotify = TaskNotify(
        id=task.id, created_at=task.created_at, header=task_create
    )
    await topic_publisher.publish(
        routing_key=str(rk),  # "srv.a3b0000000c99999d250813.tsk",
        message=notify,
        exchange=settings.rmq.x_name,
        correlation_id=task.id,
        headers={"method_code": str(notify.header.method_code)},
    )
    # await send_welcome_email.kiq(user_id=user.id)
    return task


@router.get("/{id}", response_model=TaskResponseResult)
async def get_task(
    id: UUID4,
    session: Annotated[
        AsyncSession,
        Depends(db_helper.session_getter),
    ],
    org_id: Annotated[int | None, Header()] = None,
) -> TaskResponseResult:  # TaskResponseStatus:
    task = await TasksRepository.get_task(session, id, org_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


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
    task: TaskResponseDeleted = await TasksRepository.delete_task(session, id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
