import os
import uuid
import logging
import logging.handlers
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

import pytest


class _DummyRotatingFileHandler(logging.Handler):
    def __init__(self, *args, **kwargs):
        super().__init__()


logging.handlers.RotatingFileHandler = _DummyRotatingFileHandler
Path.mkdir = lambda self, mode=0o777, parents=False, exist_ok=False: None

os.environ.setdefault(
    "APP_CONFIG__FASTSTREAM__URL", "amqp://user:pass@localhost:5672//"
)
os.environ.setdefault(
    "APP_CONFIG__DB__URL", "postgresql+asyncpg://user:pass@localhost:5432/postgres"
)
os.environ.setdefault("APP_CONFIG__LEO4__URL", "https://example.com")
os.environ.setdefault("APP_CONFIG__LEO4__API_KEY", "test-api-key")
os.environ.setdefault("APP_CONFIG__LEO4__ADMIN_URL", "https://example.com/admin")
os.environ.setdefault("APP_CONFIG__LEO4__CERT_URL", "https://example.com/cert")
os.environ.setdefault("APP_CONFIG__AUTH__API_KEYS", "test-key:1")

from core.models.common import TaskStatus
from core.schemas.device_tasks import TaskHeader, TaskResponsePayload
from core.services.device_tasks import DeviceTasksService


def _build_task(task_id: uuid.UUID, method_code: int = 20) -> TaskResponsePayload:
    return TaskResponsePayload(
        header=TaskHeader(
            ext_task_id="ext-1",
            device_id=1,
            method_code=method_code,
            priority=0,
            ttl=5,
        ),
        id=task_id,
        status=TaskStatus.READY,
        created_at=0,
        pending_at=None,
        locked_at=None,
        payload={"dt": [{"mt": 0}]},
    )


@pytest.mark.asyncio
async def test_select_treats_zero_uuid_as_polling_request():
    service = DeviceTasksService(session=object(), org_id=0)
    msg = SimpleNamespace(headers={})
    selected_task = _build_task(uuid.uuid4())

    with (
        patch(
            "core.services.device_tasks.TasksRepository.select_task",
            new=AsyncMock(return_value=selected_task),
        ) as select_task,
        patch(
            "core.services.device_tasks.TasksRepository.task_status_update",
            new=AsyncMock(),
        ) as task_status_update,
        patch("core.services.device_tasks.send_rsp", new=AsyncMock()) as send_rsp,
    ):
        await service.select("SN-1", uuid.UUID(int=0), msg)

    select_task.assert_awaited_once_with(service.session, None, "SN-1", 2999)
    task_status_update.assert_awaited_once_with(
        service.session, selected_task.id, TaskStatus.LOCK
    )
    send_rsp.assert_awaited_once_with(
        "SN-1",
        selected_task.model_dump(mode="json"),
        selected_task.id,
        selected_task.header.ttl * 60_000,
        str(selected_task.header.method_code),
    )


@pytest.mark.asyncio
async def test_select_falls_back_to_polling_when_requested_task_is_missing():
    service = DeviceTasksService(session=object(), org_id=0)
    msg = SimpleNamespace(headers={})
    requested_task_id = uuid.uuid4()
    fallback_task = _build_task(uuid.uuid4())

    with (
        patch(
            "core.services.device_tasks.TasksRepository.select_task",
            new=AsyncMock(side_effect=[None, fallback_task]),
        ) as select_task,
        patch(
            "core.services.device_tasks.TasksRepository.task_status_update",
            new=AsyncMock(),
        ) as task_status_update,
        patch("core.services.device_tasks.send_rsp", new=AsyncMock()) as send_rsp,
    ):
        await service.select("SN-1", requested_task_id, msg)

    assert select_task.await_args_list == [
        call(service.session, requested_task_id, "SN-1", 2999),
        call(service.session, None, "SN-1", 2999),
    ]
    task_status_update.assert_awaited_once_with(
        service.session, fallback_task.id, TaskStatus.LOCK
    )
    send_rsp.assert_awaited_once_with(
        "SN-1",
        fallback_task.model_dump(mode="json"),
        fallback_task.id,
        fallback_task.header.ttl * 60_000,
        str(fallback_task.header.method_code),
    )


@pytest.mark.asyncio
async def test_select_keeps_direct_task_lookup_when_task_exists():
    service = DeviceTasksService(session=object(), org_id=0)
    msg = SimpleNamespace(headers={})
    requested_task_id = uuid.uuid4()
    selected_task = _build_task(requested_task_id, method_code=51)

    with (
        patch(
            "core.services.device_tasks.TasksRepository.select_task",
            new=AsyncMock(return_value=selected_task),
        ) as select_task,
        patch(
            "core.services.device_tasks.TasksRepository.task_status_update",
            new=AsyncMock(),
        ) as task_status_update,
        patch("core.services.device_tasks.send_rsp", new=AsyncMock()) as send_rsp,
    ):
        await service.select("SN-1", requested_task_id, msg)

    select_task.assert_awaited_once_with(
        service.session, requested_task_id, "SN-1", 2999
    )
    task_status_update.assert_awaited_once_with(
        service.session, selected_task.id, TaskStatus.LOCK
    )
    send_rsp.assert_awaited_once_with(
        "SN-1",
        selected_task.model_dump(mode="json"),
        selected_task.id,
        selected_task.header.ttl * 60_000,
        str(selected_task.header.method_code),
    )
