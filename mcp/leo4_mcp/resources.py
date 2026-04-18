"""MCP resources for LEO4 platform data."""
from __future__ import annotations
import json
from typing import Any

from .client import get_client
from .config import settings
from .dry_run import dry_devices

METHOD_CODES: dict[int, dict[str, Any]] = {
    20: {
        "name": "Short command / Hello",
        "description": "Ping device or request data list. Use mt=0 for hello, mt=4 for cell list.",
        "example_payload": {"dt": [{"mt": 0}]},
    },
    21: {
        "name": "Reboot",
        "description": "Reboot the device.",
        "example_payload": {"dt": [{"mt": 0}]},
    },
    51: {
        "name": "Open cell",
        "description": "Open cell N. Replace N with the cell number.",
        "example_payload": {"dt": [{"cl": 5}]},
    },
    16: {
        "name": "Bind card / PIN",
        "description": "Bind a card or PIN code to a cell.",
        "example_payload": {"dt": [{"cl": 5, "cd": "1234"}]},
    },
    49: {
        "name": "Write NVS",
        "description": "Write a value to NVS (non-volatile storage).",
        "example_payload": {"dt": [{"ns": "app", "k": "cfg_key", "v": "value", "t": "str"}]},
    },
    50: {
        "name": "Read NVS",
        "description": "Read a value from NVS.",
        "example_payload": {"dt": [{"ns": "app", "k": "cfg_key"}]},
    },
}

EVENT_TYPES: dict[int, dict[str, Any]] = {
    13: {
        "name": "CellOpenEvent",
        "description": "Physical cell opening confirmation. tag=304 contains the cell number.",
        "key_tags": {304: "Cell number that was opened"},
    },
    1: {
        "name": "DeviceConnectEvent",
        "description": "Device connected to the platform.",
        "key_tags": {},
    },
    2: {
        "name": "DeviceDisconnectEvent",
        "description": "Device disconnected from the platform.",
        "key_tags": {},
    },
    3: {
        "name": "HealthCheckEvent",
        "description": "Periodic health/heartbeat event from device.",
        "key_tags": {301: "Battery level", 302: "Signal strength", 303: "Temperature"},
    },
}


async def get_devices_resource() -> str:
    """Return list of known/available devices as JSON."""
    if settings.dry_run:
        return json.dumps(dry_devices(), ensure_ascii=False)
    if settings.known_devices:
        return json.dumps(settings.known_devices, ensure_ascii=False)
    try:
        client = get_client()
        devices = await client.get("/devices/")
        return json.dumps(devices, ensure_ascii=False)
    except Exception as exc:
        return json.dumps(
            {"error": str(exc), "hint": "Set LEO4_KNOWN_DEVICES env var as JSON array"},
            ensure_ascii=False,
        )


async def get_device_events_resource(device_id: int, last_minutes: int = 10) -> str:
    """Return recent events for a device as JSON."""
    if settings.dry_run:
        from .dry_run import dry_get_recent_events
        return json.dumps(dry_get_recent_events(), ensure_ascii=False)
    try:
        client = get_client()
        events = await client.get(
            "/device-events/fields/",
            params={"device_id": device_id, "interval_m": last_minutes, "limit": 100},
        )
        return json.dumps(events, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def get_method_codes_resource() -> str:
    """Return method code reference as JSON."""
    return json.dumps(METHOD_CODES, ensure_ascii=False, indent=2)


def get_event_types_resource() -> str:
    """Return event type reference as JSON."""
    return json.dumps(EVENT_TYPES, ensure_ascii=False, indent=2)
