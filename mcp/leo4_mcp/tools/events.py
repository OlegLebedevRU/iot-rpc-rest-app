"""MCP tools for device events."""
from __future__ import annotations
import asyncio
import time
from typing import Optional

from ..client import get_client
from ..config import settings
from ..dry_run import dry_event_fields, dry_get_recent_events


def _check_device(device_id: int) -> None:
    allowed = settings.allowed_device_ids
    if allowed and device_id not in allowed:
        raise ValueError(
            f"device_id {device_id} is not in LEO4_ALLOWED_DEVICE_IDS={allowed}"
        )


async def get_recent_events(
    device_id: int,
    event_type_code: Optional[int] = None,
    tag: Optional[int] = None,
    interval_m: int = 5,
    limit: int = 50,
) -> list:
    """
    Fetch recent events for a device via GET /device-events/fields/.

    Args:
        device_id: LEO4 device identifier
        event_type_code: Filter by event type (e.g. 13=CellOpenEvent)
        tag: Filter by tag number (e.g. 304=cell number)
        interval_m: Look back this many minutes (default 5)
        limit: Maximum events to return (default 50)

    Returns:
        List of event field objects with value, created_at, interval_sec
    """
    _check_device(device_id)
    if settings.dry_run:
        return dry_event_fields()

    params: dict = {
        "device_id": device_id,
        "interval_m": interval_m,
        "limit": limit,
    }
    if event_type_code is not None:
        params["event_type_code"] = event_type_code
    if tag is not None:
        params["tag"] = tag

    client = get_client()
    return await client.get("/device-events/fields/", params=params)


async def get_telemetry(
    device_id: int,
    event_type_code: Optional[int] = None,
    interval_m: int = 60,
    limit: int = 100,
) -> list:
    """
    Retrieve telemetry events for a device via GET /device-events/fields/.

    Use this to get recent sensor readings, status updates, or health metrics.

    Args:
        device_id: LEO4 device identifier
        event_type_code: Filter by specific telemetry event type
        interval_m: Look back this many minutes (default 60)
        limit: Maximum events (default 100)

    Returns:
        List of telemetry event objects
    """
    _check_device(device_id)
    if settings.dry_run:
        return dry_get_recent_events()

    params: dict = {
        "device_id": device_id,
        "interval_m": interval_m,
        "limit": limit,
    }
    if event_type_code is not None:
        params["event_type_code"] = event_type_code

    client = get_client()
    return await client.get("/device-events/fields/", params=params)


async def poll_device_event(
    device_id: int,
    event_type_code: int,
    tag: int,
    expected_value: Optional[int] = None,
    interval_m: int = 5,
    timeout_s: int = 30,
) -> dict:
    """
    Poll GET /device-events/fields/ until a matching event is found or timeout.

    Use after create_device_task + get_task_status (status=3) to confirm
    physical execution. For example:
      event_type_code=13, tag=304, expected_value=5 → cell 5 physically opened.

    IMPORTANT: This uses polling (sleep 2s between requests). For production,
    prefer configure_webhook with event_type="msg-event".

    Args:
        device_id: LEO4 device identifier
        event_type_code: Event type to watch (e.g. 13=CellOpenEvent)
        tag: Tag number to filter (e.g. 304=cell number)
        expected_value: If set, only match events where value==expected_value
        interval_m: Look-back window for each poll (default 5)
        timeout_s: Total seconds to wait (default 30)

    Returns:
        {"confirmed": True, "event": {...}} if found, or
        {"confirmed": False, "message": "..."} on timeout
    """
    _check_device(device_id)
    if settings.dry_run:
        return {"confirmed": True, "event": dry_event_fields()[0]}

    client = get_client()
    deadline = time.monotonic() + timeout_s
    params = {
        "device_id": device_id,
        "event_type_code": event_type_code,
        "tag": tag,
        "interval_m": interval_m,
        "limit": 50,
    }

    while time.monotonic() < deadline:
        rows = await client.get("/device-events/fields/", params=params)
        for row in rows:
            v = row.get("value")
            if expected_value is None or v == expected_value:
                return {"confirmed": True, "event": row}
        await asyncio.sleep(2)

    return {
        "confirmed": False,
        "event_type_code": event_type_code,
        "tag": tag,
        "expected_value": expected_value,
        "message": f"No matching event found within {timeout_s}s",
    }
