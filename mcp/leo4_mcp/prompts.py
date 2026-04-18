"""MCP prompts for common LEO4 scenarios."""
from __future__ import annotations
from mcp.server.fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    @mcp.prompt()
    def open_cell(device_id: int, cell_number: int) -> str:
        """Prompt template for opening a specific cell on a device."""
        return (
            f"Please open cell {cell_number} on device {device_id}.\n\n"
            "Steps to follow:\n"
            "1. Call create_device_task with method_code=51 and "
            f'payload={{"dt": [{{"cl": {cell_number}}}]}}\n'
            "2. Call get_task_status to confirm delivery (status=3 = DONE = delivered only)\n"
            "3. Call poll_device_event with event_type_code=13, tag=304, "
            f"expected_value={cell_number} to confirm physical opening\n\n"
            "Or use the composite tool open_cell_and_confirm which does all three steps.\n\n"
            "IMPORTANT: Do NOT report success until poll_device_event confirms the cell "
            "physically opened (confirmed=True)."
        )

    @mcp.prompt()
    def diagnose_device(device_id: int) -> str:
        """Prompt template for device diagnostics."""
        return (
            f"Please run a diagnostic check on device {device_id}.\n\n"
            "Steps to follow:\n"
            f"1. Call hello({device_id}) to check connectivity\n"
            f"2. Call get_recent_events(device_id={device_id}, interval_m=60) "
            "to check last hour events\n"
            f"3. Call get_telemetry(device_id={device_id}, interval_m=60) "
            "to get latest sensor/health data\n"
            "4. Report: connectivity status, last event time, any errors or anomalies\n\n"
            "Flag any issues like: no events in last hour, repeated disconnect events, "
            "low battery, or failed tasks."
        )

    @mcp.prompt()
    def mass_open_cells(device_ids: str, cell_number: int) -> str:
        """Prompt for opening cells on multiple devices. device_ids: comma-separated list."""
        return (
            f"Please open cell {cell_number} on the following devices: {device_ids}.\n\n"
            "Use mass_activate with:\n"
            f"  device_ids = [{device_ids}]\n"
            "  method_code = 51\n"
            f'  payload = {{"dt": [{{"cl": {cell_number}}}]}}\n\n'
            "After mass_activate completes, report how many devices succeeded vs failed.\n"
            "IMPORTANT: mass_activate results show delivery status only. "
            "Physical confirmation requires polling events per device."
        )
