"""Deterministic mock responses for LEO4_DRY_RUN=1."""
from __future__ import annotations
import time
from typing import Any

MOCK_TASK_ID = "00000000-0000-0000-0000-000000000001"

DRY_TASK = {
    "id": MOCK_TASK_ID,
    "created_at": int(time.time()),
    "status": 3,
    "status_name": "DONE",
    "device_id": 0,
    "method_code": 20,
    "ttl": 5,
    "priority": 1,
    "ext_task_id": "dry-run-task",
    "payload": None,
    "results": [],
}

DRY_EVENT_FIELDS = [
    {
        "value": 5,
        "created_at": "2026-01-01T00:00:00Z",
        "interval_sec": 10,
    }
]

DRY_EVENTS = [
    {
        "id": 1,
        "device_id": 0,
        "event_type_code": 13,
        "created_at": "2026-01-01T00:00:00Z",
        "data": {"304": 5},
    }
]

DRY_WEBHOOK = {
    "id": 1,
    "event_type": "msg-event",
    "url": "https://example.com/hook",
    "headers": {},
    "is_active": True,
}

DRY_DEVICES = [
    {"id": 0, "name": "dry-run-device", "status": "online"}
]


def dry_create_task(device_id: int, method_code: int, **_: Any) -> dict:
    t = dict(DRY_TASK)
    t["device_id"] = device_id
    t["method_code"] = method_code
    t["created_at"] = int(time.time())
    return t


def dry_get_task(_task_id: str) -> dict:
    return dict(DRY_TASK)


def dry_list_tasks(_device_id: int) -> dict:
    return {"items": [DRY_TASK], "total": 1, "page": 1, "size": 1, "pages": 1}


def dry_event_fields(**_: Any) -> list:
    return list(DRY_EVENT_FIELDS)


def dry_get_recent_events(**_: Any) -> list:
    return list(DRY_EVENTS)


def dry_webhook(**_: Any) -> dict:
    return dict(DRY_WEBHOOK)


def dry_list_webhooks() -> list:
    return [DRY_WEBHOOK]


def dry_devices() -> list:
    return list(DRY_DEVICES)
