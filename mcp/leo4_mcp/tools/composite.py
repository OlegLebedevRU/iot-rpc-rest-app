"""Composite MCP tools that combine multiple LEO4 API calls."""
from __future__ import annotations
import asyncio
from typing import Optional

from .tasks import create_device_task, get_task_status, _check_device
from .events import poll_device_event


async def hello(device_id: int) -> dict:
    """
    Send a hello/ping to an IoT device (method_code=20).

    Creates a hello task and waits for delivery confirmation.
    DONE (status=3) = delivered, not physically executed.

    Args:
        device_id: LEO4 device identifier

    Returns:
        Task status object after delivery
    """
    task = await create_device_task(
        device_id=device_id,
        method_code=20,
        payload={"dt": [{"mt": 0}]},
        ttl=5,
    )
    task_id = task["id"]
    return await get_task_status(task_id)


async def open_cell_and_confirm(
    device_id: int,
    cell_number: int,
    ttl: int = 5,
    timeout_s: int = 30,
) -> dict:
    """
    Full 3-step cycle: send open-cell command → confirm delivery → confirm physical opening.

    Step 1: POST /device-tasks/ with method_code=51
    Step 2: GET /device-tasks/{id} until status=3 (DONE = delivered)
    Step 3: GET /device-events/fields/ polling until CellOpenEvent (code=13, tag=304)
            with value==cell_number is received

    IMPORTANT: status=3 alone does NOT mean the cell opened physically.
    This composite tool waits for the physical event before returning confirmed=True.

    Args:
        device_id: LEO4 device identifier
        cell_number: Cell number to open (e.g. 5)
        ttl: Task TTL in minutes (default 5)
        timeout_s: Seconds to wait for physical confirmation (default 30)

    Returns:
        {
          "task": {...},
          "delivery": {"status": 3, "status_name": "DONE", ...},
          "physical_confirmation": {"confirmed": True/False, "event": {...}}
        }
    """
    task = await create_device_task(
        device_id=device_id,
        method_code=51,
        payload={"dt": [{"cl": cell_number}]},
        ttl=ttl,
    )
    task_id = task["id"]

    delivery = await get_task_status(task_id)

    confirmation = await poll_device_event(
        device_id=device_id,
        event_type_code=13,
        tag=304,
        expected_value=cell_number,
        timeout_s=timeout_s,
    )

    return {
        "task": task,
        "delivery": delivery,
        "physical_confirmation": confirmation,
    }


async def reboot_device(device_id: int, ttl: int = 5) -> dict:
    """
    Reboot a device (method_code=21).

    Creates reboot task and returns delivery status.
    Physical reboot is confirmed by the device reconnecting; no event polling needed.

    Args:
        device_id: LEO4 device identifier
        ttl: Task TTL in minutes (default 5)

    Returns:
        Task status after delivery
    """
    task = await create_device_task(
        device_id=device_id,
        method_code=21,
        payload={"dt": [{"mt": 0}]},
        ttl=ttl,
    )
    return await get_task_status(task["id"])


async def bind_card_to_cell(
    device_id: int,
    cell_number: int,
    card_code: str,
    ttl: int = 5,
) -> dict:
    """
    Bind a card/PIN code to a cell (method_code=16).

    Args:
        device_id: LEO4 device identifier
        cell_number: Target cell number
        card_code: Card or PIN code to bind
        ttl: Task TTL in minutes (default 5)

    Returns:
        Task status after delivery
    """
    task = await create_device_task(
        device_id=device_id,
        method_code=16,
        payload={"dt": [{"cl": cell_number, "cd": card_code}]},
        ttl=ttl,
    )
    return await get_task_status(task["id"])


async def write_nvs(
    device_id: int,
    namespace: str,
    key: str,
    value: str,
    type: str,
    ttl: int = 5,
) -> dict:
    """
    Write a value to NVS (Non-Volatile Storage) on a device (method_code=49).

    Args:
        device_id: LEO4 device identifier
        namespace: NVS namespace
        key: NVS key
        value: Value to write
        type: NVS value type (e.g. "str", "i32", "blob")
        ttl: Task TTL in minutes (default 5)

    Returns:
        Task status after delivery
    """
    task = await create_device_task(
        device_id=device_id,
        method_code=49,
        payload={"dt": [{"ns": namespace, "k": key, "v": value, "t": type}]},
        ttl=ttl,
    )
    return await get_task_status(task["id"])


async def read_nvs(
    device_id: int,
    namespace: str,
    key: str,
    ttl: int = 5,
) -> dict:
    """
    Read a value from NVS (Non-Volatile Storage) on a device (method_code=50).

    Args:
        device_id: LEO4 device identifier
        namespace: NVS namespace
        key: NVS key to read
        ttl: Task TTL in minutes (default 5)

    Returns:
        Task object with results containing the NVS value
    """
    task = await create_device_task(
        device_id=device_id,
        method_code=50,
        payload={"dt": [{"ns": namespace, "k": key}]},
        ttl=ttl,
    )
    return await get_task_status(task["id"])


async def mass_activate(
    device_ids: list[int],
    method_code: int,
    payload: dict,
    ttl: int = 5,
) -> dict:
    """
    Send the same command to multiple devices in parallel using asyncio.gather.

    Uses concurrent POST /device-tasks/ requests for all device IDs.
    IMPORTANT: status=3 for each device means delivery only.

    Args:
        device_ids: List of LEO4 device identifiers
        method_code: Command code to send to all devices
        payload: Command parameters
        ttl: Task TTL in minutes (default 5)

    Returns:
        {
          "total": N,
          "success": M,
          "failed": K,
          "results": [{"device_id": ..., "task": {...}} or {"device_id": ..., "error": "..."}]
        }
    """
    async def _one(device_id: int) -> dict:
        try:
            task = await create_device_task(
                device_id=device_id,
                method_code=method_code,
                payload=payload,
                ttl=ttl,
            )
            return {"device_id": device_id, "task": task}
        except Exception as exc:
            return {"device_id": device_id, "error": str(exc)}

    results = await asyncio.gather(*[_one(d) for d in device_ids])
    success = sum(1 for r in results if "task" in r)
    return {
        "total": len(device_ids),
        "success": success,
        "failed": len(device_ids) - success,
        "results": list(results),
    }
