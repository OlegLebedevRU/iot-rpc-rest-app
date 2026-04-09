import json
from uuid import UUID

from fastapi import HTTPException
from fastapi_pagination import Page
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.crud.dev_tasks_repo import TasksRepository
from core.crud.device_repo import DeviceRepo
from core.logging_config import setup_module_logger
from core.models.common import TaskStatus
from core.schemas.device_tasks import (
    TaskCreate,
    TaskListOut,
    TaskResponseResult,
    TaskResponseDeleted,
    TaskHeader,
    ResultArray,
    TaskResponse,
    TaskResponsePayload,
)
from core.services.device_task_processing import send_tsk, send_rsp, send_cmt

log = setup_module_logger(__name__, "srv_dev_tasks.log")


async def act_ttl():
    pass


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

        task = TaskResponse(id=db_uuid, created_at=created_at)
        log.info("Created task %s", task)
        await send_tsk(sn, task_create, task)
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

    @staticmethod
    def _get_method_limit(msg) -> int:
        ws_count = 0
        if hasattr(msg, "headers"):
            msg_headers = msg.headers
            if "slave_ws" in msg_headers:
                ws_count = int(msg_headers["slave_ws"])
        return 3999 if ws_count > 0 else 2999

    @staticmethod
    def _build_task_response(task_data: dict) -> TaskResponsePayload:
        return TaskResponsePayload(
            header=TaskHeader.model_validate(task_data),
            id=task_data["id"],
            status=task_data["status"],
            created_at=task_data["created_at"],
            pending_at=task_data["pending_at"],
            locked_at=task_data["locked_at"],
            payload=task_data["payload"],
        )

    async def _select_task(
        self, sn: str, corr_id: UUID4 | None, method_le: int
    ) -> TaskResponsePayload | None:
        if corr_id is None or corr_id == settings.task_proc_cfg.zero_corr_id:
            task_data = await TasksRepository.select_next_task_by_sn(
                self.session, sn, method_le
            )
        else:
            task_data = await TasksRepository.select_task_by_id(
                self.session, corr_id, method_le
            )

        if task_data is None:
            return None

        return self._build_task_response(task_data)

    async def select(self, sn, corr_id: UUID4, msg):
        method_le = self._get_method_limit(msg)
        task = await self._select_task(sn, corr_id, method_le)
        if task is not None:
            t_resp = task.model_dump(mode="json")
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

        await send_rsp(sn, t_resp, correlation_id, expiration, method_code)

    async def save(self, msg, sn, corr_id: UUID4):
        ext_id = int(msg.headers.get("ext_id", 0))
        status_code = int(msg.headers.get("status_code", 501))

        if not corr_id:
            log.info(
                "Mqtt received RESULT with ERROR <dev.%s.res> - No corr_id, ext_id=%d, status_code=%d",
                sn,
                ext_id,
                status_code,
            )
            return

        # Декодируем тело
        raw_body = msg.body.decode() if msg.body else "{}"

        # Пытаемся распарсить как JSON
        try:
            res_data = json.loads(raw_body)
            if not isinstance(res_data, dict):
                res_data = {"result": res_data}
        except (json.JSONDecodeError, TypeError):
            res_data = {"result": raw_body}

        log.info(
            "Mqtt received RESULT ext_id=%d, status_code=%d, parsed result: %s",
            ext_id,
            status_code,
            res_data,
        )

        result_id = await TasksRepository.save_task_result(
            self.session, corr_id, ext_id, status_code, res_data
        )

        rmsg = "committed"
        try:
            await TasksRepository.task_status_update(
                self.session, corr_id, TaskStatus.DONE
            )
        except Exception as e:
            log.error("Task status update error %s", e)
            rmsg = "Partial error: result committed, but status update failed"

        cmt_payload = {"message": rmsg}
        dev_id = await DeviceRepo.get_device_id(session=self.session, sn=sn)
        await send_cmt(
            sn,
            cmt_payload,
            json.dumps(res_data),
            corr_id,
            dev_id,
            result_id,
            ext_id,
            status_code,
        )

    async def ttl(self, decrement: int = 1):
        await TasksRepository.update_ttl(self.session, decrement)
        log.info("Complited job event, decrement TTL = %d", decrement)
