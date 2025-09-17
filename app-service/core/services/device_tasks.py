import logging
from typing import Annotated
from uuid import UUID

from fastapi import HTTPException, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import session

from core.config import RoutingKey, settings
from core.crud.dev_tasks_repo import TasksRepository
from core.crud.device_repo import DeviceRepo
from core.models import db_helper
from core.schemas.device_tasks import TaskCreate, TaskNotify
from core.topologys.fs_queues import topic_publisher

log = logging.getLogger(__name__)


class DeviceTasksService:
    def __init__(self, session, org_id):
        self.session: AsyncSession = session
        self.org_id = org_id

    # @classmethod
    async def create_task(self, task_create: TaskCreate):
        sn = await DeviceRepo.get_device_sn(
            session=self.session, device_id=task_create.device_id, org_id=self.org_id
        )
        if sn is None:
            log.info(
                "trying to create task failed - device_id not found = %d",
                task_create.device_id,
            )
            raise HTTPException(status_code=404, detail="device_id not found")
        task = await TasksRepository.create_task(
            session=self.session,
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

    # @classmethod
    async def get(self, id: UUID):
        task = await TasksRepository.get_task(self.session, id, self.org_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task
