import logging
import uuid
from typing import Annotated, List, Sequence

from fastapi import (
    APIRouter,
    Depends, HTTPException,
)
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession
from core import settings
from core.config import RoutingKey
from core.crud.dev_tasks_repo import TasksRepository
from core.models import db_helper
from core.schemas.device_tasks import (
    TaskCreate,
    TaskResponseStatus,
    TaskResponse,
    TaskRequest,
    TaskResponseResult, TaskResponseDeleted
)
from core.topology.fs_queues import topic_publisher

#from crud import users as users_crud

log = logging.getLogger(__name__)
router = APIRouter(
    prefix=settings.api.v1.device_tasks,
    tags=["Device tasks"],)

#
# @router.get("", response_model=list[UserRead])
# async def get_users(
#     # session: AsyncSession = Depends(db_helper.session_getter),
#     session: Annotated[
#         AsyncSession,
#         Depends(db_helper.session_getter),
#     ],
# ):
#     users = await users_crud.get_all_users(session=session)
#     return users
#
#
@router.post("/", response_model=TaskResponse)
async def create_task(
    session: Annotated[
        AsyncSession,
        Depends(db_helper.session_getter),
    ],
    task_create: TaskCreate,
):
    task = await TasksRepository.create_task(
        session=session,
        task=task_create,
    )
    log.info("Created task %s", task)
    t=repr(task_create)
    rk=RoutingKey(settings.rmq.prefix_srv,
                  "a3b0000000c99999d250813", settings.rmq.suffix_task)
    await topic_publisher.publish(
        routing_key=  str(rk),#"srv.a3b0000000c99999d250813.task",
        message=f"from api with amqp publish, task ={t}"
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


@router.get("/", response_model=Sequence[TaskResponseStatus],
            description=f"Tasks search by device_id with limit = {settings.db.limit_tasks_result}" )
async def get_tasks(session: Annotated[AsyncSession, Depends(db_helper.session_getter)],
                    device_id: int | None = 0):  #TaskResponseStatus:
    task:Sequence[TaskResponseStatus] = await TasksRepository.get_tasks(session, device_id)
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
