from __future__ import annotations

from dataclasses import dataclass

CMD_DIAG_STREAM_CONTROL = 7000
CMD_DIAG_EXEC = 7001
CMD_DIAG_CANCEL = 7002

DIAGNOSTICS_MIN_METHOD_CODE = 7000
DIAGNOSTICS_MAX_METHOD_CODE = 7099

DEFAULT_LIVE_LOG_TTL_SEC = 300
DEFAULT_DIAG_EXEC_TTL_SEC = 60
DEFAULT_MAX_OUTPUT_BYTES = 1_048_576
DEFAULT_MAX_RATE_BPS = 8_192


@dataclass(frozen=True, slots=True)
class DiagnosticCommandSpec:
    command_id: str
    description: str


# Backend-side allowlist for public API validation. Device agents still keep their
# own local allowlist and must reject unsupported command_id values.
DIAGNOSTIC_COMMANDS: dict[str, DiagnosticCommandSpec] = {
    # Basic / cross-platform
    "system_info": DiagnosticCommandSpec(
        command_id="system_info",
        description="Basic OS, kernel/firmware and hardware summary.",
    ),
    "echo": DiagnosticCommandSpec(
        command_id="echo",
        description="Echo back the supplied arguments; connectivity/latency check.",
    ),
    "time": DiagnosticCommandSpec(
        command_id="time",
        description="Return current device clock time.",
    ),
    # Universal (any platform)
    "network_info": DiagnosticCommandSpec(
        command_id="network_info",
        description="Network interface, route and DNS diagnostics.",
    ),
    "disk_usage": DiagnosticCommandSpec(
        command_id="disk_usage",
        description="Filesystem usage summary.",
    ),
    "service_status": DiagnosticCommandSpec(
        command_id="service_status",
        description="Agent/application service status summary.",
    ),
    # Linux
    "uptime": DiagnosticCommandSpec(
        command_id="uptime",
        description="System uptime and load average.",
    ),
    "memory_usage": DiagnosticCommandSpec(
        command_id="memory_usage",
        description="RAM and swap usage statistics.",
    ),
    "process_list": DiagnosticCommandSpec(
        command_id="process_list",
        description="Full process list snapshot.",
    ),
    "top_processes": DiagnosticCommandSpec(
        command_id="top_processes",
        description="Top CPU/memory consuming processes.",
    ),
    "journal_logs": DiagnosticCommandSpec(
        command_id="journal_logs",
        description="Recent systemd journal log entries.",
    ),
    "iptables_rules": DiagnosticCommandSpec(
        command_id="iptables_rules",
        description="Active iptables/nftables firewall rules.",
    ),
    "systemctl_status": DiagnosticCommandSpec(
        command_id="systemctl_status",
        description="Status of a specific systemd unit.",
    ),
    # Windows
    "get_processes": DiagnosticCommandSpec(
        command_id="get_processes",
        description="Running process list (Windows).",
    ),
    "get_services": DiagnosticCommandSpec(
        command_id="get_services",
        description="Windows service list and their states.",
    ),
    "event_log": DiagnosticCommandSpec(
        command_id="event_log",
        description="Recent Windows Event Log entries.",
    ),
    "disk_info": DiagnosticCommandSpec(
        command_id="disk_info",
        description="Disk partition and volume information (Windows).",
    ),
    "cpu_usage": DiagnosticCommandSpec(
        command_id="cpu_usage",
        description="CPU utilisation snapshot.",
    ),
    "network_config": DiagnosticCommandSpec(
        command_id="network_config",
        description="Network adapter configuration (Windows ipconfig).",
    ),
    "os_version": DiagnosticCommandSpec(
        command_id="os_version",
        description="Detailed OS version and build information.",
    ),
    "mssql_query": DiagnosticCommandSpec(
        command_id="mssql_query",
        description="Execute a predefined MSSQL diagnostic query via the device agent.",
    ),
    # Utility
    "list_commands": DiagnosticCommandSpec(
        command_id="list_commands",
        description="Return the list of command_id values supported by the device agent.",
    ),
    "raw_cmd": DiagnosticCommandSpec(
        command_id="raw_cmd",
        description="Execute custom Windows command line via cmd.exe or powershell.",
    ),
    "raw_command": DiagnosticCommandSpec(
        command_id="raw_command",
        description="Execute custom Windows command line.",
    ),
}


def is_known_command(command_id: str) -> bool:
    if command_id in ("raw_cmd", "raw_command", "custom", "cli", "exec"):
        return True
    return command_id in DIAGNOSTIC_COMMANDS
