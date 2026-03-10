from uuid import UUID

from fastapi import HTTPException
from fastapi_pagination import Page
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import RoutingKey, settings
from core.crud.dev_tasks_repo import TasksRepository
from core.crud.device_repo import DeviceRepo

# from core.fs_broker import fs_router
from core.logging_config import setup_module_logger
from core.models.common import TaskStatus
from core.schemas.device_tasks import (
    TaskCreate,
    TaskNotify,
    TaskListOut,
    TaskResponseResult,
    TaskResponseDeleted,
    TaskHeader,
    ResultArray,
    TaskResponse,
)
from core.schemas.rmq_admin import RmqClientsAction
from core.topologys.declare import topic_exchange, def_x, job_publisher, topic_publisher

topology = settings.rmq

# job_publisher = fs_router.publisher()
# topic_publisher = fs_router.publisher()
log = setup_module_logger(__name__, "srv_dev_tasks.log")


async def act_ttl(step: int):
    await job_publisher.publish(
        message="ttl_decrement",
        routing_key=settings.ttl_job.queue_name,
        expiration=1 * 60_000,
    )

    # api_test_msg: RmqClientsAction = RmqClientsAction(
    #     action="get_online_status",
    #     clients=[
    #         "a1b0004617c24558d080925",
    #         "a3b0000000c10221d290825",
    #     ],
    # )
    api_test2_msg: RmqClientsAction = RmqClientsAction(
        action="update_online_status", clients=[]
    )
    await job_publisher.publish(
        routing_key=settings.rmq.api_clients_queue,
        message=api_test2_msg,
        expiration=1 * 60_000,
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
        db_uuid, created_at = await TasksRepository.create_task(
            session=self.session,
            task=task_create,
        )
        task = TaskResponse(id=db_uuid, created_at=int(created_at))
        log.info("Created task %s", task)
        task_device_topic = str(
            RoutingKey(settings.rmq.prefix_srv, sn, settings.rmq.suffix_task)
        )
        notify: TaskNotify = TaskNotify(
            id=task.id, created_at=task.created_at, header=task_create
        )
        await topic_publisher.publish(
            routing_key=task_device_topic,  # "srv.a3b0000000c99999d250813.tsk",
            message=notify,
            exchange=topic_exchange,  # settings.rmq.x_name,
            correlation_id=task.id,
            expiration=task_create.ttl * 60_000,
            headers={
                "method_code": str(notify.header.method_code),
                "correlationData": str(task.id),
            },
        )
        return task

    # @classmethod
    async def get(self, id: UUID) -> TaskResponseResult | None:
        # Получаем задачу и результаты из репозитория
        task_data, results_data = await TasksRepository.get_task(
            self.session, id, self.org_id
        )

        # Проверяем существование задачи
        if task_data is None:
            raise HTTPException(status_code=404, detail="Task not found")

        # Валидируем основные данные задачи
        header = TaskHeader.model_validate(task_data)

        # Обрабатываем результаты выполнения
        results = []
        if results_data:
            for result_item in results_data:
                results.append(ResultArray.model_validate(result_item))

        # Создаем ответную модель
        task_response = TaskResponseResult(
            header=header,
            id=task_data["id"],
            status=task_data["status"],
            created_at=int(task_data["created_at"]),
            pending_at=(
                int(task_data["pending_at"])
                if task_data["pending_at"] is not None
                else None
            ),
            locked_at=(
                int(task_data["locked_at"])
                if task_data["locked_at"] is not None
                else None
            ),
            results=results,
        )

        return task_response

    async def delete(self, id: UUID) -> TaskResponseDeleted:
        task: TaskResponseDeleted = await TasksRepository.delete_task(
            self.session, id, self.org_id
        )
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    async def list(self, device_id: int) -> Page[TaskListOut]:
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

    async def select(self, sn, corr_id: UUID4, msg):
        ws_count = 0
        if hasattr(msg, "headers"):
            msg_headers = msg.headers
            if "slave_ws" in msg_headers:
                ws_count = int(msg_headers["slave_ws"])
        if ws_count > 0:
            method_le = 3999
        else:
            method_le = 2999
        task = await TasksRepository.select_task(self.session, corr_id, sn, method_le)
        if task is not None:
            t_resp = task.model_dump_json()
            log.info("from DB select task = %s", t_resp)
            method_code = str(task.header.method_code)
            await TasksRepository.task_status_update(
                self.session, task.id, TaskStatus.LOCK
            )
            correlation_id = task.id
            expiration = task.header.ttl * 60_000  # Use actual TTL
        else:
            t_resp = settings.task_proc_cfg.nop_resp
            log.debug("from DB select task = None")
            correlation_id = settings.task_proc_cfg.zero_corr_id
            method_code = "0"
            expiration = 3 * 60 * 1000  # Fallback TTL: 3 minutes (or use config)

        routing_key: str = str(
            RoutingKey(
                prefix=topology.prefix_srv, sn=sn, suffix=topology.suffix_response
            )
        )
        await topic_publisher.publish(
            routing_key=routing_key,
            message=t_resp,
            correlation_id=correlation_id,  # str(correlation_id),uuid.UUID(correlation_id).bytes,
            exchange=topic_exchange,  # settings.rmq.x_name,
            expiration=expiration,
            headers={
                "method_code": method_code,
                "correlationData": str(correlation_id),
            },
        )

    async def save(self, msg, sn, corr_id: UUID4):
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
            log.info(
                "Mqtt received RESULT ext_id=%d, status_code=%d",
                ext_id,
                status_code,
            )

            result_id = await TasksRepository.save_task_result(
                self.session, corr_id, ext_id, status_code, res
            )
            rmsg = "commited"
            try:
                await TasksRepository.task_status_update(
                    self.session, corr_id, TaskStatus.DONE
                )
            except Exception as e:
                log.error("Task status update error %s", e)
                rmsg = "Partial error= result commited, but status updated fail"
        else:

            log.info(
                "Mqtt received RESULT with ERROR <dev.%s.res> - No corr_id, ext_id=%d, status_code=%d",
                sn,
                ext_id,
                status_code,
            )
            return
        routing_key: str = str(
            RoutingKey(
                prefix=topology.prefix_srv, sn=sn, suffix=topology.suffix_commited
            )
        )
        await topic_publisher.publish(
            routing_key=routing_key,
            message=rmsg,
            correlation_id=corr_id,
            exchange=topic_exchange,  # settings.rmq.x_name,
            expiration=180 * 60_000,
            headers={
                "ext_id": str(ext_id),
                "result_id": str(result_id),
                "correlationData": str(corr_id),
            },
        )
        dev_id = await DeviceRepo.get_device_id(session=self.session, sn=sn)
        await topic_publisher.publish(
            routing_key=settings.webhook.webhooks_queue,  # "srv.a3b0000000c99999d250813.tsk",
            message=msg.body,
            exchange=def_x,  # settings.rmq.x_name_direct,
            correlation_id=corr_id,
            expiration=30 * 60_000,
            headers={
                "x-device-id": str(dev_id),
                "x-msg-type": "msg-task-result",
                "x-ext-id": str(ext_id),
                "x-result-id": str(result_id),
            },
        )

    async def ttl(self, decrement: int = 1):
        await TasksRepository.update_ttl(self.session, decrement)
        log.info("Complited job event, decrement TTL = %d", decrement)
