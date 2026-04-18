"""FastMCP server for LEO4 IoT platform."""
from __future__ import annotations
import json
import logging

from mcp.server.fastmcp import FastMCP

from .config import settings
from .resources import (
    get_devices_resource,
    get_device_events_resource,
    get_method_codes_resource,
    get_event_types_resource,
)
from .prompts import register_prompts
from .tools.tasks import create_device_task, get_task_status, list_device_tasks
from .tools.events import poll_device_event, get_recent_events, get_telemetry
from .tools.webhooks import configure_webhook, list_webhooks
from .tools.composite import (
    hello,
    open_cell_and_confirm,
    reboot_device,
    bind_card_to_cell,
    write_nvs,
    read_nvs,
    mass_activate,
)

log = logging.getLogger(__name__)

mcp = FastMCP(
    "leo4-mcp",
    instructions=(
        "You control IoT devices via the LEO4 platform REST API. "
        "IMPORTANT: task status=3 (DONE) means the command was DELIVERED to the device only, "
        "NOT that it was physically executed. "
        "Always use poll_device_event or open_cell_and_confirm to verify physical actions. "
        "Use composite tools (open_cell_and_confirm, reboot_device, etc.) to avoid mistakes."
    ),
)

# ── Register tools ────────────────────────────────────────────────────────────

mcp.tool()(create_device_task)
mcp.tool()(get_task_status)
mcp.tool()(list_device_tasks)
mcp.tool()(poll_device_event)
mcp.tool()(get_recent_events)
mcp.tool()(get_telemetry)
mcp.tool()(configure_webhook)
mcp.tool()(list_webhooks)
mcp.tool()(hello)
mcp.tool()(open_cell_and_confirm)
mcp.tool()(reboot_device)
mcp.tool()(bind_card_to_cell)
mcp.tool()(write_nvs)
mcp.tool()(read_nvs)
mcp.tool()(mass_activate)

# ── Register resources ────────────────────────────────────────────────────────

@mcp.resource("leo4://devices")
async def devices_resource() -> str:
    """List of LEO4 devices available to this organisation."""
    return await get_devices_resource()


@mcp.resource("leo4://devices/{device_id}/events")
async def device_events_resource(device_id: int) -> str:
    """Recent events for a specific device (last 10 minutes)."""
    return await get_device_events_resource(device_id)


@mcp.resource("leo4://method-codes")
def method_codes_resource() -> str:
    """Reference: method_code → command description + example payload."""
    return get_method_codes_resource()


@mcp.resource("leo4://event-types")
def event_types_resource() -> str:
    """Reference: event_type_code → description + key tags."""
    return get_event_types_resource()

# ── Register prompts ──────────────────────────────────────────────────────────

register_prompts(mcp)

log.info(
    "LEO4 MCP server initialised | dry_run=%s | api_url=%s",
    settings.dry_run,
    settings.api_url,
)
