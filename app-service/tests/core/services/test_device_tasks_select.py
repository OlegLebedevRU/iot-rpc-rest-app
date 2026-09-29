import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest


from core.models.common import TaskStatus
from core.crud.dev_tasks_repo import StoredTaskResult, TasksRepository
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

    await service.select(
        "SN_TEST", device_tasks_module.settings.task_proc_cfg.zero_corr_id, msg
    )

    select_next_task_by_sn.assert_awaited_once_with(session, "SN_TEST", 2999)
    select_task_by_id.assert_not_called()
    task_status_update.assert_awaited_once_with(
        session, task_id, TaskStatus.LOCK, sn="SN_TEST"
    )
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
        5 * 60,
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

    select_task_by_id.assert_awaited_once_with(session, corr_id, 7099, sn="SN_TEST")
    select_next_task_by_sn.assert_not_called()
    task_status_update.assert_not_called()
    send_rsp.assert_awaited_once_with(
        "SN_TEST",
        device_tasks_module.settings.task_proc_cfg.nop_resp,
        device_tasks_module.settings.task_proc_cfg.zero_corr_id,
        3 * 60,
        "0",
    )


@pytest.mark.asyncio
async def test_triggered_select_allows_diagnostics_without_slave_ws_header(monkeypatch):
    session = object()
    service = DeviceTasksService(session, 0)
    corr_id = uuid4()
    msg = SimpleNamespace(headers={})

    select_task_by_id = AsyncMock(return_value=None)
    select_next_task_by_sn = AsyncMock()
    send_rsp = AsyncMock()

    monkeypatch.setattr(
        device_tasks_module.TasksRepository, "select_task_by_id", select_task_by_id
    )
    monkeypatch.setattr(
        device_tasks_module.TasksRepository,
        "select_next_task_by_sn",
        select_next_task_by_sn,
    )
    monkeypatch.setattr(device_tasks_module, "send_rsp", send_rsp)

    await service.select("SN_TEST", corr_id, msg)

    select_task_by_id.assert_awaited_once_with(session, corr_id, 7099, sn="SN_TEST")
    select_next_task_by_sn.assert_not_called()


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

    record_result = AsyncMock()
    task_status_update = AsyncMock()
    get_device_id = AsyncMock()
    send_cmt = AsyncMock()

    monkeypatch.setattr(
        device_tasks_module.TasksRepository, "record_result", record_result
    )
    monkeypatch.setattr(
        device_tasks_module.TasksRepository, "task_status_update", task_status_update
    )
    monkeypatch.setattr(device_tasks_module.DeviceRepo, "get_device_id", get_device_id)
    monkeypatch.setattr(device_tasks_module, "send_cmt", send_cmt)

    result = await service.save(
        msg,
        "SN_TEST",
        device_tasks_module.settings.task_proc_cfg.zero_corr_id,
    )

    assert result is False
    record_result.assert_not_called()
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
        body=b'{"description":"partial"}',
    )
    record_result = AsyncMock(return_value=None)
    send_cmt = AsyncMock()
    monkeypatch.setattr(TasksRepository, "record_result", record_result)
    monkeypatch.setattr(device_tasks_module, "send_cmt", send_cmt)

    assert await service.save(msg, "SN_TEST", corr_id) is False
    args = record_result.await_args.args
    assert args[:7] == (
        session,
        corr_id,
        "SN_TEST",
        12345,
        206,
        {"description": "partial"},
        None,
    )
    assert isinstance(args[7], datetime)
    send_cmt.assert_not_called()


@pytest.mark.asyncio
async def test_save_new_result_sends_cmt_and_webhook(monkeypatch):
    session = object()
    service = DeviceTasksService(session, 0)
    corr_id = uuid4()
    uid = uuid4()
    payload = {"description": "result"}
    msg = SimpleNamespace(
        headers={"ext_id": "123", "status_code": "200", "result_uid": str(uid)},
        body=b'{"description":"result"}',
    )
    record_result = AsyncMock(
        return_value=StoredTaskResult(77, 123, 200, payload, True, True)
    )
    get_device_id = AsyncMock(return_value=501)
    send_cmt = AsyncMock()
    monkeypatch.setattr(TasksRepository, "record_result", record_result)
    monkeypatch.setattr(device_tasks_module.DeviceRepo, "get_device_id", get_device_id)
    monkeypatch.setattr(device_tasks_module, "send_cmt", send_cmt)

    assert await service.save(msg, "SN_TEST", corr_id) is True
    assert record_result.await_args.args[:7] == (
        session,
        corr_id,
        "SN_TEST",
        123,
        200,
        payload,
        uid,
    )
    send_cmt.assert_awaited_once_with(
        "SN_TEST",
        {"message": "committed"},
        json.dumps(payload),
        corr_id,
        501,
        77,
        123,
        200,
        send_webhook=False,
        result_uid=uid,
    )


@pytest.mark.asyncio
async def test_duplicate_result_only_resends_cmt(monkeypatch):
    session = object()
    service = DeviceTasksService(session, 0)
    corr_id = uuid4()
    msg = SimpleNamespace(
        headers={"ext_id": "bad", "status_code": "200", "result_uid": "invalid"},
        body=b'{"corr_id":"' + str(corr_id).encode() + b'","result":{"status":"ok"}}',
    )
    record_result = AsyncMock(
        return_value=StoredTaskResult(77, 0, 200, {"status": "ok"}, False, False)
    )
    monkeypatch.setattr(TasksRepository, "record_result", record_result)
    monkeypatch.setattr(
        device_tasks_module.DeviceRepo, "get_device_id", AsyncMock(return_value=501)
    )
    send_cmt = AsyncMock()
    monkeypatch.setattr(device_tasks_module, "send_cmt", send_cmt)

    assert await service.save(msg, "SN_TEST", corr_id) is False
    assert record_result.await_args.args[:7] == (
        session,
        corr_id,
        "SN_TEST",
        0,
        200,
        {"status": "ok"},
        None,
    )
    assert send_cmt.await_args.kwargs == {"send_webhook": False, "result_uid": None}


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
async def test_get_task_normalizes_list_result_payload(monkeypatch):
    session = object()
    service = DeviceTasksService(session, 0)
    task_id = uuid4()
    task_data = build_task_data(task_id)
    results_data = [
        {
            "id": 1,
            "ext_id": 12345,
            "status_code": 200,
            "result": [{"k": "send_options", "t": "i32", "v": 1}],
        }
    ]

    get_task = AsyncMock(return_value=(task_data, results_data))
    monkeypatch.setattr(device_tasks_module.TasksRepository, "get_task", get_task)

    task_response = await service.get(task_id)

    assert task_response.results[0].result == {
        "value": [{"k": "send_options", "t": "i32", "v": 1}]
    }


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


def test_repository_normalize_result_for_storage_wraps_non_dict_values():
    assert TasksRepository._normalize_result_for_storage(
        [{"k": "send_options", "t": "i32", "v": 1}]
    ) == {"value": [{"k": "send_options", "t": "i32", "v": 1}]}
    assert TasksRepository._normalize_result_for_storage("plain text") == {
        "value": "plain text"
    }
    assert TasksRepository._normalize_result_for_storage("123") == {"value": 123}
    assert TasksRepository._normalize_result_for_storage(None) == {"value": None}
    assert TasksRepository._normalize_result_for_storage({"status": "OK"}) == {
        "status": "OK"
    }


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
    assert "ceil(" in compiled
    assert "created_at ASC" in compiled
