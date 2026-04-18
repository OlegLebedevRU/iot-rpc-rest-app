"""MCP tools for device tasks."""
from __future__ import annotations
import uuid
from typing import Any, Optional

from ..client import get_client, Leo4ApiError
from ..config import settings
from .. import dry_run as _dry


def _check_device(device_id: int) -> None:
    allowed = settings.allowed_device_ids
    if allowed and device_id not in allowed:
        raise ValueError(
            f"device_id {device_id} is not in LEO4_ALLOWED_DEVICE_IDS={allowed}. "
            "Add it to the allowlist to proceed."
        )


async def create_device_task(
    device_id: int,
    method_code: int,
    payload: Optional[dict] = None,
    ttl: int = 5,
    priority: int = 1,
    ext_task_id: Optional[str] = None,
) -> dict:
    """
    Create a task for an IoT device via LEO4 POST /device-tasks/.

    IMPORTANT: A successful response means the task was accepted by the server.
    status=3 (DONE) returned by get_task_status means the command was DELIVERED
    to the device – it does NOT mean the command was physically executed.
    For physical confirmation (e.g. cell opened), use poll_device_event or
    the open_cell_and_confirm composite tool.

    Args:
        device_id: LEO4 device identifier
        method_code: Command code (20=hello, 21=reboot, 51=open cell, 16=bind card,
                     49=write NVS, 50=read NVS)
        payload: Command parameters, e.g. {"dt": [{"cl": 5}]} to open cell 5
        ttl: Task time-to-live in minutes (default 5)
        priority: Task priority 0-9 (default 1)
        ext_task_id: Your idempotency key; auto-generated UUID if not provided

    Returns:
        {"id": "<uuid>", "created_at": <timestamp>}
    """
    _check_device(device_id)
    if settings.dry_run:
        return _dry.dry_create_task(device_id, method_code)

    body: dict[str, Any] = {
        "device_id": device_id,
        "method_code": method_code,
        "ttl": ttl,
        "priority": priority,
        "ext_task_id": ext_task_id or str(uuid.uuid4()),
    }
    if payload is not None:
        body["payload"] = payload

    client = get_client()
    return await client.post("/device-tasks/", json=body)


async def get_task_status(task_id: str) -> dict:
    """
    Get task status via LEO4 GET /device-tasks/{id}.

    Status codes:
      0 = READY (waiting for device)
      1 = PENDING (device acknowledged)
      2 = LOCK (device executing)
      3 = DONE (command DELIVERED – not physically executed!)
      4 = EXPIRED (TTL elapsed)
      5 = DELETED
      6 = FAILED

    IMPORTANT: DONE (3) means delivery only. Use poll_device_event or
    open_cell_and_confirm to confirm physical execution.

    Args:
        task_id: UUID of the task returned by create_device_task

    Returns:
        Full task object with status, status_name, results
    """
    if settings.dry_run:
        return _dry.dry_get_task(task_id)

    client = get_client()
    return await client.get(f"/device-tasks/{task_id}")


async def list_device_tasks(device_id: int, limit: int = 50) -> dict:
    """
    List tasks for a device via LEO4 GET /device-tasks/?device_id=N.

    Args:
        device_id: LEO4 device identifier
        limit: Maximum results per page (default 50)

    Returns:
        Paginated list of tasks
    """
    _check_device(device_id)
    if settings.dry_run:
        return _dry.dry_list_tasks(device_id)

    client = get_client()
    return await client.get("/device-tasks/", params={"device_id": device_id, "size": limit})
