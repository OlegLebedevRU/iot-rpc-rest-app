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
    "system_info": DiagnosticCommandSpec(
        command_id="system_info",
        description="Basic OS, kernel/firmware and hardware summary.",
    ),
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
    "mssql_query": DiagnosticCommandSpec(
        command_id="mssql_query",
        description="Execute predefined MSSQL diagnostic query via device agent.",
    ),
}


def is_known_command(command_id: str) -> bool:
    return command_id in DIAGNOSTIC_COMMANDS
