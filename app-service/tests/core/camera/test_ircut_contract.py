from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.camera.ircut_contract import REVISION, require_ircut, validate_ircut
from core.camera.admission import admit_task
from core.camera.task_route import CameraTaskRoute
from core.config import settings
from core.schemas.device_tasks import TaskCreate


def item(action="start"):
    result = {
        "ircut_revision": REVISION,
        "action": action,
        "camera_mac": "00:12:34:a2:de:b9",
    }
    if action != "inspect":
        result["session_id"] = "11111111-1111-4111-8111-111111111111"
    if action in ("start", "apply"):
        result.update(
            boot_id="22222222-2222-4222-8222-222222222222",
            expected_revision="a" * 64,
            allow_disruptive=True,
        )
    return result


@pytest.mark.parametrize("method", [168, 169])
@pytest.mark.parametrize("action", ["inspect", "start", "status", "cancel", "recover"])
def test_registered(method, action):
    payload = {"dt": [item(action)]}
    task = TaskCreate(
        ext_task_id="ircut", device_id=4623, method_code=method, payload=payload
    )
    assert task.payload == payload
    assert "camera_contract_revision" not in task.model_dump()


@pytest.mark.parametrize(
    "key,value",
    [
        ("shell", "anything"),
        ("password", "synthetic"),
        ("camera_mac", "01:12:34:a2:de:b9"),
        ("camera_mac", "00:00:00:00:00:00"),
        ("allow_disruptive", 1),
        ("allow_disruptive", False),
        ("budget_ms", True),
        ("budget_ms", 999),
        ("budget_ms", 2147483648),
        ("expected_revision", "a" * 63),
        ("session_id", "not-a-uuid"),
        ("ircut_revision", "unknown"),
        ("pairs", [[42, 42]]),
        ("pairs", [[42, 43], [43, 42]]),
        ("pairs", [[True, 43]]),
        ("pairs", []),
    ],
)
def test_reject_unsafe_or_malformed(key, value):
    value_item = item()
    value_item[key] = value
    with pytest.raises(ValueError):
        validate_ircut(168, {"dt": [value_item]})


def test_diagnostics_has_no_replacement_or_apply():
    value = item()
    value["pairs"] = [[42, 43]]
    with pytest.raises(ValueError):
        validate_ircut(169, {"dt": [value]})
    with pytest.raises(ValueError):
        validate_ircut(169, {"dt": [item("apply")]})
    with pytest.raises(ValidationError):
        TaskCreate(
            ext_task_id="ircut",
            device_id=4623,
            method_code=168,
            camera_contract_revision="siplite-camera/1.0.0",
            payload={"dt": [item()]},
        )


def observation():
    return {**item(), "methods": [168, 169], "revision": "a" * 64}


def test_gate_and_cleanup(monkeypatch):
    monkeypatch.setattr(settings.camera, "writers_enabled", False)
    with pytest.raises(HTTPException, match="camera_writers_disabled"):
        require_ircut(168, item(), observation())
    for action in ("inspect", "status", "cancel", "recover"):
        require_ircut(169, item(action), observation())
    monkeypatch.setattr(settings.camera, "writers_enabled", True)
    require_ircut(168, item(), observation())


@pytest.mark.parametrize(
    "field,value",
    [
        ("boot_id", "old"),
        ("revision", "b" * 64),
        ("methods", [160]),
        ("camera_mac", "00:12:34:a2:de:ba"),
    ],
)
def test_capability_conflicts(monkeypatch, field, value):
    monkeypatch.setattr(settings.camera, "writers_enabled", True)
    obs = deepcopy(observation())
    obs[field] = value
    with pytest.raises(HTTPException):
        require_ircut(168, item(), obs)


def test_old_firmware_cannot_receive_ircut():
    with pytest.raises(HTTPException, match="ircut_contract_not_negotiated"):
        require_ircut(169, item("inspect"), None)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "action,enabled,expected",
    [
        ("start", False, "camera_writers_disabled"),
        ("start", True, None),
        ("inspect", False, None),
        ("recover", False, None),
    ],
)
async def test_registered_admission_uses_online_gauge(
    action, enabled, expected, monkeypatch
):
    monkeypatch.setattr(settings.camera, "writers_enabled", enabled)
    task = TaskCreate(
        ext_task_id="ircut",
        device_id=4623,
        method_code=169,
        payload={"dt": [item(action)]},
    )
    gauge = SimpleNamespace(
        updated_at=datetime.now(UTC),
        gauges={"300": [{"450": {"ircut": observation()}}]},
    )
    connection = SimpleNamespace(app_connect=True, is_blocked=False)
    session = SimpleNamespace(scalar=AsyncMock(side_effect=[connection, gauge]))
    if expected:
        with pytest.raises(HTTPException, match=expected):
            await admit_task(session, task, "synthetic-sn")
    else:
        await admit_task(session, task, "synthetic-sn")
    gauge.updated_at -= timedelta(seconds=61)
    with pytest.raises(HTTPException, match="camera_capabilities_stale"):
        await admit_task(
            SimpleNamespace(scalar=AsyncMock(side_effect=[connection, gauge])),
            task,
            "synthetic-sn",
        )


@pytest.mark.parametrize("method", [168, 169])
@pytest.mark.parametrize("action", ["inspect", "status", "start", "cancel", "recover"])
def test_viewer_can_inspect_but_not_actuate(method, action):
    app = FastAPI()
    router = APIRouter(route_class=CameraTaskRoute)

    @router.post("/tasks")
    async def accept(task: TaskCreate):
        return {"method": task.method_code}

    app.include_router(router)
    response = TestClient(app).post(
        "/tasks",
        headers={"X-Role": "viewer"},
        json={
            "ext_task_id": "ircut",
            "device_id": 4623,
            "method_code": method,
            "payload": {"dt": [item(action)]},
        },
    )
    assert response.status_code == (200 if action in ("inspect", "status") else 403)
