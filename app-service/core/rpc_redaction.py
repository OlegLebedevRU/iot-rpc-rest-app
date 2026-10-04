"""Redact credential fields without changing the payload delivered to devices."""

from typing import Any
import re

SENSITIVE_FIELDS = frozenset({"pin", "password", "secret", "token", "private_key"})


def redact_rpc(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "***"
            if str(key).lower() in SENSITIVE_FIELDS
            or (
                str(key).lower() == "command_line"
                and isinstance(item, str)
                and re.search(r"(?i)(?:^|[\\/\s\"])l4pin(?:\.exe)?(?:[\"\s]|$)", item)
            )
            else redact_rpc(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_rpc(item) for item in value]
    return value
