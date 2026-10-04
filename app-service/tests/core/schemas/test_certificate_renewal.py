from datetime import UTC, datetime
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from core.schemas.device_tasks import TaskCreate
from core.services.device_tasks import DeviceTasksService
from core.crud.dev_tasks_repo import TasksRepository


@pytest.mark.parametrize("ttl", [0, 1, 2, 3])
@pytest.mark.parametrize("remaining", [-1, 30, 120, 180])
def test_renewal_queue_deadline_matrix(ttl, remaining):
    expiry = int(datetime.now(UTC).timestamp()) + remaining
    value = dict(
        device_id=1,
        ext_task_id="fixture",
        method_code=7011,
        ttl=ttl,
        payload={"dt": [{"pin": "000000", "pin_expires_at": expiry}]},
    )
    valid = ttl > 0 and ttl * 60 < remaining
    if valid:
        assert TaskCreate(**value).payload["dt"][0]["ttl_sec"] == 120
    else:
        with pytest.raises(ValidationError):
            TaskCreate(**value)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"dt": []},
        {"dt": {}},
        {"dt": ["000000"]},
        {"dt": [{"pin": "123", "pin_expires_at": 4102444800}]},
        {
            "dt": [
                {
                    "pin": "000000",
                    "pin_expires_at": 4102444800,
                    "operation_id": "forbidden",
                }
            ]
        },
        {"dt": [{"pin": "000000", "pin_expires_at": 4102444800, "ttl_sec": 30}]},
    ],
)
def test_renewal_rejects_noncanonical_or_unbounded_body(payload):
    with pytest.raises(ValidationError):
        TaskCreate(
            device_id=1, ext_task_id="fixture", method_code=7011, ttl=1, payload=payload
        )


@pytest.mark.anyio
async def test_service_polling_only_claims_advertised_methods(monkeypatch):
    from core.services import device_tasks as module

    repository = AsyncMock(return_value=None)
    monkeypatch.setattr(module.TasksRepository, "select_next_task_by_sn", repository)
    monkeypatch.setattr(module, "send_rsp", AsyncMock())
    session = object()
    await DeviceTasksService(session, 0).select(
        "fixture",
        module.settings.task_proc_cfg.zero_corr_id,
        SimpleNamespace(headers={"rpc_methods": "7001,7002,7003,7011"}),
    )
    repository.assert_awaited_once_with(
        session, "fixture", 7011, method_codes={7001, 7002, 7003, 7011}
    )


@pytest.mark.anyio
async def test_scrub_targets_one_task_and_only_renewal_payload():
    session = SimpleNamespace(execute=AsyncMock())
    task_id = uuid4()
    await TasksRepository.scrub_renewal_payload(session, [task_id])
    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "task_id IN" in sql and "method_code =" in sql
    assert statement.compile().params["payload"] == {"dt": []}


def test_history_payload_redaction_keeps_delivery_separate():
    from core.schemas.device_tasks import TaskResponseResult, TaskResponsePayload
    from datetime import datetime, UTC

    envelope = {
        "id": "135a4120-9ba6-4f6c-8cac-4baf5df8f1df",
        "created_at": int(datetime.now(UTC).timestamp()),
        "status": 0,
        "header": {"ext_task_id": "fixture", "device_id": 773, "method_code": 7011},
        "payload": {
            "dt": [{"pin": "000000", "pin_expires_at": 4102444800, "ttl_sec": 120}]
        },
    }
    history = TaskResponseResult.model_validate({**envelope, "results": []})
    delivery = TaskResponsePayload.model_validate(envelope)
    assert history.payload["dt"][0]["pin"] == "***"
    assert delivery.payload["dt"][0]["pin"] == "000000"


def test_renewal_console_arguments_are_not_history_credentials():
    from core.rpc_redaction import redact_rpc

    assert redact_rpc(
        {"dt": [{"command_line": "l4pin --renew-authenticated --pin 000000"}]}
    ) == {"dt": [{"command_line": "***"}]}
    assert redact_rpc({"command_line": "echo normal"})["command_line"] == "echo normal"
