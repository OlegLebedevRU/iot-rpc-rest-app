import logging
import logging.handlers
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault(
    "APP_CONFIG__FASTSTREAM__URL", "amqp://user:pass@localhost:5672//"
)
os.environ.setdefault(
    "APP_CONFIG__DB__URL", "postgresql+asyncpg://user:pass@localhost:5432/postgres"
)
os.environ.setdefault("APP_CONFIG__AUTH__API_KEYS", "test:1")
os.environ.setdefault("APP_CONFIG__LEO4__URL", "http://localhost")
os.environ.setdefault("APP_CONFIG__LEO4__API_KEY", "x")
os.environ.setdefault("APP_CONFIG__LEO4__ADMIN_URL", "http://localhost")
os.environ.setdefault("APP_CONFIG__LEO4__CERT_URL", "http://localhost")

logging.handlers.RotatingFileHandler = lambda *args, **kwargs: logging.NullHandler()
Path.mkdir = lambda self, mode=0o777, parents=False, exist_ok=False: None

from core.models.common import TaskStatus
from core.crud.dev_tasks_repo import TasksRepository
from core.services import device_tasks as device_tasks_module
from core.services.device_tasks import DeviceTasksService
from core.topologys.fs_depends import corr_id_getter_dep


def build_task_data(task_id):
    return {
        "id": task_id,
        "ext_task_id": "ext-1",
        "method_code": 51,
        "device_id": 100,
        "created_at": 1712345678,
        "priority": 1,
        "status": TaskStatus.READY,
        "pending_at": None,
        "locked_at": None,
        "ttl": 5,
        "payload": {"dt": [{"cl": 5}]},
    }


class EmptyMappingsResult:
    def one_or_none(self):
        return None


class EmptyExecuteResult:
    def mappings(self):
        return EmptyMappingsResult()


@pytest.mark.asyncio
async def test_select_uses_sn_polling_for_zero_uuid(monkeypatch):
    session = object()
    service = DeviceTasksService(session, 0)
    task_id = uuid4()
    msg = SimpleNamespace(headers={})

    select_next_task_by_sn = AsyncMock(return_value=build_task_data(task_id))
    select_task_by_id = AsyncMock()
    task_status_update = AsyncMock()
    send_rsp = AsyncMock()

    monkeypatch.setattr(
        device_tasks_module.TasksRepository,
        "select_next_task_by_sn",
        select_next_task_by_sn,
    )
    monkeypatch.setattr(
        device_tasks_module.TasksRepository, "select_task_by_id", select_task_by_id
    )
    monkeypatch.setattr(
        device_tasks_module.TasksRepository, "task_status_update", task_status_update
    )
    monkeypatch.setattr(device_tasks_module, "send_rsp", send_rsp)

    await service.select("SN_TEST", device_tasks_module.settings.task_proc_cfg.zero_corr_id, msg)

    select_next_task_by_sn.assert_awaited_once_with(session, "SN_TEST", 2999)
    select_task_by_id.assert_not_called()
    task_status_update.assert_awaited_once_with(session, task_id, TaskStatus.LOCK)
    send_rsp.assert_awaited_once_with(
        "SN_TEST",
        {
            "header": {
                "ext_task_id": "ext-1",
                "device_id": 100,
                "method_code": 51,
                "priority": 1,
                "ttl": 5,
            },
            "id": str(task_id),
            "created_at": 1712345678,
            "status": TaskStatus.READY,
            "pending_at": None,
            "locked_at": None,
            "payload": {"dt": [{"cl": 5}]},
        },
        task_id,
        5 * 60_000,
        "51",
    )


@pytest.mark.asyncio
async def test_select_uses_task_lookup_for_non_zero_uuid(monkeypatch):
    session = object()
    service = DeviceTasksService(session, 0)
    corr_id = uuid4()
    msg = SimpleNamespace(headers={"slave_ws": "1"})

    select_task_by_id = AsyncMock(return_value=None)
    select_next_task_by_sn = AsyncMock()
    task_status_update = AsyncMock()
    send_rsp = AsyncMock()

    monkeypatch.setattr(
        device_tasks_module.TasksRepository, "select_task_by_id", select_task_by_id
    )
    monkeypatch.setattr(
        device_tasks_module.TasksRepository,
        "select_next_task_by_sn",
        select_next_task_by_sn,
    )
    monkeypatch.setattr(
        device_tasks_module.TasksRepository, "task_status_update", task_status_update
    )
    monkeypatch.setattr(device_tasks_module, "send_rsp", send_rsp)

    await service.select("SN_TEST", corr_id, msg)

    select_task_by_id.assert_awaited_once_with(session, corr_id, 3999)
    select_next_task_by_sn.assert_not_called()
    task_status_update.assert_not_called()
    send_rsp.assert_awaited_once_with(
        "SN_TEST",
        device_tasks_module.settings.task_proc_cfg.nop_resp,
        device_tasks_module.settings.task_proc_cfg.zero_corr_id,
        3 * 60 * 1000,
        "0",
    )


@pytest.mark.asyncio
async def test_pending_skips_status_update_for_zero_uuid(monkeypatch):
    session = object()
    service = DeviceTasksService(session, 0)
    task_status_update = AsyncMock()

    monkeypatch.setattr(
        device_tasks_module.TasksRepository, "task_status_update", task_status_update
    )

    await service.pending(device_tasks_module.settings.task_proc_cfg.zero_corr_id)

    task_status_update.assert_not_called()


@pytest.mark.asyncio
async def test_save_skips_result_processing_for_zero_uuid(monkeypatch):
    session = object()
    service = DeviceTasksService(session, 0)
    msg = SimpleNamespace(
        headers={"ext_id": "12345", "status_code": "206"},
        body=b'{"description": "from device partial result"}',
    )

    save_task_result = AsyncMock()
    task_status_update = AsyncMock()
    get_device_id = AsyncMock()
    send_cmt = AsyncMock()

    monkeypatch.setattr(
        device_tasks_module.TasksRepository, "save_task_result", save_task_result
    )
    monkeypatch.setattr(
        device_tasks_module.TasksRepository, "task_status_update", task_status_update
    )
    monkeypatch.setattr(device_tasks_module.DeviceRepo, "get_device_id", get_device_id)
    monkeypatch.setattr(device_tasks_module, "send_cmt", send_cmt)

    await service.save(
        msg,
        "SN_TEST",
        device_tasks_module.settings.task_proc_cfg.zero_corr_id,
    )

    save_task_result.assert_not_called()
    task_status_update.assert_not_called()
    get_device_id.assert_not_called()
    send_cmt.assert_not_called()


@pytest.mark.asyncio
async def test_save_skips_finalization_for_missing_task(monkeypatch):
    session = object()
    service = DeviceTasksService(session, 0)
    corr_id = uuid4()
    msg = SimpleNamespace(
        headers={"ext_id": "12345", "status_code": "206"},
        body=b'{"description": "from device partial result"}',
    )

    save_task_result = AsyncMock(return_value=None)
    task_status_update = AsyncMock()
    get_device_id = AsyncMock()
    send_cmt = AsyncMock()

    monkeypatch.setattr(
        device_tasks_module.TasksRepository, "save_task_result", save_task_result
    )
    monkeypatch.setattr(
        device_tasks_module.TasksRepository, "task_status_update", task_status_update
    )
    monkeypatch.setattr(device_tasks_module.DeviceRepo, "get_device_id", get_device_id)
    monkeypatch.setattr(device_tasks_module, "send_cmt", send_cmt)

    await service.save(msg, "SN_TEST", corr_id)

    save_task_result.assert_awaited_once_with(
        session,
        corr_id,
        12345,
        206,
        {"description": "from device partial result"},
    )
    task_status_update.assert_not_called()
    get_device_id.assert_not_called()
    send_cmt.assert_not_called()


@pytest.mark.asyncio
async def test_save_finalizes_existing_task(monkeypatch):
    session = object()
    service = DeviceTasksService(session, 0)
    corr_id = uuid4()
    msg = SimpleNamespace(
        headers={"ext_id": "12345", "status_code": "200"},
        body=b'{"description": "from device final result"}',
    )

    save_task_result = AsyncMock(return_value=77)
    task_status_update = AsyncMock(return_value=True)
    get_device_id = AsyncMock(return_value=501)
    send_cmt = AsyncMock()

    monkeypatch.setattr(
        device_tasks_module.TasksRepository, "save_task_result", save_task_result
    )
    monkeypatch.setattr(
        device_tasks_module.TasksRepository, "task_status_update", task_status_update
    )
    monkeypatch.setattr(device_tasks_module.DeviceRepo, "get_device_id", get_device_id)
    monkeypatch.setattr(device_tasks_module, "send_cmt", send_cmt)

    await service.save(msg, "SN_TEST", corr_id)

    save_task_result.assert_awaited_once_with(
        session,
        corr_id,
        12345,
        200,
        {"description": "from device final result"},
    )
    task_status_update.assert_awaited_once_with(session, corr_id, TaskStatus.DONE)
    get_device_id.assert_awaited_once_with(session=session, sn="SN_TEST")
    send_cmt.assert_awaited_once_with(
        "SN_TEST",
        {"message": "committed"},
        '{"description": "from device final result"}',
        corr_id,
        501,
        77,
        12345,
        200,
    )


@pytest.mark.asyncio
async def test_save_strips_transport_corr_wrapper_from_result(monkeypatch):
    session = object()
    service = DeviceTasksService(session, 0)
    corr_id = uuid4()
    msg = SimpleNamespace(
        headers={"ext_id": "12345", "status_code": "200"},
        body=(
            b'{"corr_data":"'
            + str(corr_id).encode("utf-8")
            + b'","result":{"description":"from device final result"}}'
        ),
    )

    save_task_result = AsyncMock(return_value=77)
    task_status_update = AsyncMock(return_value=True)
    get_device_id = AsyncMock(return_value=501)
    send_cmt = AsyncMock()

    monkeypatch.setattr(
        device_tasks_module.TasksRepository, "save_task_result", save_task_result
    )
    monkeypatch.setattr(
        device_tasks_module.TasksRepository, "task_status_update", task_status_update
    )
    monkeypatch.setattr(device_tasks_module.DeviceRepo, "get_device_id", get_device_id)
    monkeypatch.setattr(device_tasks_module, "send_cmt", send_cmt)

    await service.save(msg, "SN_TEST", corr_id)

    save_task_result.assert_awaited_once_with(
        session,
        corr_id,
        12345,
        200,
        {"description": "from device final result"},
    )


@pytest.mark.asyncio
async def test_corr_id_getter_uses_body_fallback_before_msg_correlation_id():
    body_corr_id = uuid4()
    msg = SimpleNamespace(
        headers={},
        body=f'{{"correlationData":"{body_corr_id}"}}'.encode("utf-8"),
        correlation_id=str(uuid4()),
        raw_message=SimpleNamespace(headers={}, correlation_id=None),
    )

    corr_id = await corr_id_getter_dep(msg)

    assert corr_id == body_corr_id


@pytest.mark.asyncio
async def test_repository_task_status_update_skips_zero_uuid():
    session: Any = SimpleNamespace(
        execute=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )

    updated = await TasksRepository.task_status_update(
        session,
        device_tasks_module.settings.task_proc_cfg.zero_corr_id,
        TaskStatus.PENDING,
    )

    assert updated is True
    session.execute.assert_not_called()
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_repository_save_task_result_skips_zero_uuid():
    session: Any = SimpleNamespace(
        execute=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )

    result_id = await TasksRepository.save_task_result(
        session,
        device_tasks_module.settings.task_proc_cfg.zero_corr_id,
        12345,
        206,
        {"description": "from device partial result"},
    )

    assert result_id is None
    session.execute.assert_not_called()
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_repository_save_task_result_returns_none_for_missing_task():
    session: Any = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: None)
        ),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )

    result_id = await TasksRepository.save_task_result(
        session,
        uuid4(),
        12345,
        206,
        {"description": "from device partial result"},
    )

    assert result_id is None
    session.execute.assert_awaited_once()
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_polling_query_prefers_high_priority_then_smallest_positive_ttl():
    session: Any = SimpleNamespace(execute=AsyncMock(return_value=EmptyExecuteResult()))

    await TasksRepository.select_next_task_by_sn(session, "SN_TEST", 2999)

    query = session.execute.await_args.args[0]
    compiled = str(query)

    assert "status <" in compiled
    assert "method_code <=" in compiled
    assert "ttl >" in compiled
    assert "ORDER BY" in compiled
    assert "priority DESC" in compiled
    assert "ttl ASC" in compiled
    assert "created_at ASC" in compiled
