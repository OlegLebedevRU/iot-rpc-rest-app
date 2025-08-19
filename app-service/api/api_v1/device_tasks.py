import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
)
from sqlalchemy.ext.asyncio import AsyncSession

from core import settings
from core.fs_broker import task_registered
from core.models import db_helper
from core.schemas.device_tasks import (
    TaskCreate,
    TaskResponseStatus,
TaskResponse,
TaskRequest,
TaskResponseResult
)
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
@router.post("", response_model=None)
async def create_user(
    session: Annotated[
        AsyncSession,
        Depends(db_helper.session_getter),
    ],
    task_create: TaskCreate,
):
    # user = await users_crud.create_user(
    #     session=session,
    #     user_create=user_create,
    # )
    log.info("Created task %s", 1)
    await task_registered.publish(
        exchange="amq.topic",
        message="from api with amqp publish"
    )
    # await send_welcome_email.kiq(user_id=user.id)
    return