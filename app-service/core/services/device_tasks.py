import logging
from uuid import UUID
from fastapi import HTTPException
from fastapi_pagination import Page
from sqlalchemy.ext.asyncio import AsyncSession
from core.config import RoutingKey, settings
from core.crud.dev_tasks_repo import TasksRepository
from core.crud.device_repo import DeviceRepo
from core.fs_broker import fs_router
from core.models.common import TaskStatus
from core.schemas.device_tasks import (
    TaskCreate,
    TaskNotify,
    TaskListOut,
    TaskResponseResult,
    TaskResponseDeleted,
)
from core.schemas.rmq_admin import RmqClientsAction

topology = settings.rmq

job_publisher = fs_router.publisher()
topic_publisher = fs_router.publisher()
log = logging.getLogger(__name__)


async def act_ttl(step: int):
    await job_publisher.publish(
        message="ttl_decrement", routing_key=settings.ttl_job.queue_name
    )
    # [
    #             "a1b0004617c24558d080925",
    #             "a3b0000000c10221d290825",
    #         ]
    api_test_msg: RmqClientsAction = RmqClientsAction(
        action="get_online_status",
        clients=[
            "a1b0004617c24558d080925",
            "a3b0000000c10221d290825",
        ],
    )
    await job_publisher.publish(
        routing_key=settings.rmq.ack_queue_name, message=api_test_msg
    )


class DeviceTasksService:
    def __init__(self, session, org_id):
        self.session: AsyncSession = session
        self.org_id = org_id

    # @classmethod
    async def create(self, task_create: TaskCreate):
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
    async def get(self, id: UUID) -> TaskResponseResult | None:
        task = await TasksRepository.get_task(self.session, id, self.org_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    async def delete(self, id: UUID) -> TaskResponseDeleted:
        task: TaskResponseDeleted = await TasksRepository.delete_task(
            self.session, id, self.org_id
        )
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    async def list(self, device_id) -> Page[TaskListOut]:
        tasks: Page[TaskListOut] = await TasksRepository.get_tasks(
            self.session, device_id, self.org_id
        )
        if tasks is None:
            raise HTTPException(status_code=404, detail="Tasks not found")
        return tasks

    async def pending(self, corr_id):
        if corr_id is not None:
            await TasksRepository.task_status_update(
                self.session, corr_id, TaskStatus.PENDING
            )

    async def select(self, sn, corr_id):
        task = await TasksRepository.select_task(self.session, corr_id, sn)
        if task is not None:
            t_resp = task.model_dump_json()
            logging.info("from DB select task = %s", t_resp)
            method_code = str(task.header.method_code)
            await TasksRepository.task_status_update(
                self.session, task.id, TaskStatus.LOCK
            )
            correlation_id = task.id
        else:
            t_resp = settings.task_proc_cfg.nop_resp
            logging.info("from DB select task = None")
            correlation_id = settings.task_proc_cfg.zero_corr_id
            method_code = "0"
        routing_key: str = str(
            RoutingKey(
                prefix=topology.prefix_srv, sn=sn, suffix=topology.suffix_response
            )
        )
        await topic_publisher.publish(
            routing_key=routing_key,
            message=t_resp,
            correlation_id=str(correlation_id),
            exchange=settings.rmq.x_name,
            headers={"method_code": method_code},
        )

    async def save(self, msg, sn, corr_id):
        if "ext_id" in msg.headers:
            ext_id = int(msg.headers["ext_id"])
        else:
            ext_id = 0
        if "status_code" in msg.headers:
            status_code = int(msg.headers["status_code"])
        else:
            status_code = 501
        if corr_id:
            if msg.body:
                res = msg.body.decode()
            else:
                res = "default"
            logging.info(
                "Mqtt received RESULT ext_id=%d, status_code=%d",
                ext_id,
                status_code,
            )
            await TasksRepository.save_task_result(
                self.session, corr_id, ext_id, status_code, res
            )
            await TasksRepository.task_status_update(
                self.session, corr_id, TaskStatus.DONE
            )
        else:
            logging.info(
                "Mqtt received RESULT with ERROR <dev.%s.res> - No corr_id, ext_id=%d, status_code=%d",
                sn,
                ext_id,
                status_code,
            )

    async def ttl(self, decrement: int = 1):
        await TasksRepository.update_ttl(self.session, decrement)
        logging.info("subscribe job event  decrement TTL = %d", decrement)
