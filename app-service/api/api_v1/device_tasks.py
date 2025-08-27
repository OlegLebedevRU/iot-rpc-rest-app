import logging
import uuid
from typing import Annotated, List, Sequence, Any
from fastapi import (
    APIRouter,
    Depends, HTTPException,
)
from fastapi.responses import ORJSONResponse
from pydantic import UUID4
from pydantic_core.core_schema import AnySchema
from sqlalchemy import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from core import settings
from core.config import RoutingKey
from core.crud.dev_tasks_repo import TasksRepository
from core.crud.device_repo import DeviceRepo
from core.models import db_helper
from core.schemas.device_tasks import (
    TaskCreate,
    TaskResponseStatus,
    TaskResponse,
    TaskRequest,
    TaskResponseResult, TaskResponseDeleted, TaskNotify
)
from core.topologys.fs_queues import topic_publisher

#from crud import users as users_crud

log = logging.getLogger(__name__)
router = APIRouter(
    prefix=settings.api.v1.device_tasks,
    tags=["Device tasks"],)

@router.post("/", response_model=TaskResponse)
async def create_task(
    session: Annotated[
        AsyncSession,
        Depends(db_helper.session_getter),
    ],
    task_create: TaskCreate,
):
    sn = await DeviceRepo.get_device_sn(session, task_create.device_id)
    if sn is None:
        log.info(f"trying to create task failed - device_id not found = {task_create.device_id}")
        raise HTTPException(status_code=404, detail="device_id not found")
    task = await TasksRepository.create_task(
        session=session,
        task=task_create,
    )
    log.info("Created task %s", task)
    rk=RoutingKey(settings.rmq.prefix_srv,
                  sn, settings.rmq.suffix_task)
    notify: TaskNotify = TaskNotify(id=task.id,
                                    created_at=task.created_at,
                                    header=task_create)
    await topic_publisher.publish(
        routing_key=  str(rk),#"srv.a3b0000000c99999d250813.tsk",
        message=notify,
        exchange=settings.rmq.x_name,
        correlation_id=task.id
    )
    # await send_welcome_email.kiq(user_id=user.id)
    return task

@router.get("/{id}", response_model=TaskResponseResult)
async def get_task(id: UUID4, session: Annotated[
        AsyncSession,
        Depends(db_helper.session_getter),
    ],

                   ):  #TaskResponseStatus:
    task = await TasksRepository.get_task(session, id)
    if task is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return task


@router.get("/",
            description=f"Tasks search by device_id with limit = {settings.db.limit_tasks_result}" )
async def get_tasks(session: Annotated[AsyncSession, Depends(db_helper.session_getter)],
                    device_id: int | None = 0):  #TaskResponseStatus:
    task = await TasksRepository.get_tasks(session, device_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return task


@router.delete("/{id}", response_model=TaskResponseDeleted,
               description = "soft delete")
async def delete_task(id: UUID4, session: Annotated[
        AsyncSession,
        Depends(db_helper.session_getter),
    ],):  #TaskResponseStatus:
    task = await TasksRepository.delete_task(session, id)
    if task is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return task
