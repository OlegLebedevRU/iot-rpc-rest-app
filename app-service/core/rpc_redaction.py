"""Redact credential fields without changing the payload delivered to devices."""

from typing import Any
import re

SENSITIVE_FIELDS = frozenset(
    {
        "pin",
        "password",
        "secret",
        "token",
        "private_key",
        "credentials",
        "sealed_credentials",
        "wrapped_key",
        "ciphertext",
        "nonce",
        "tag",
    }
)


def redact_rpc(value: Any) -> Any:
    if isinstance(value, dict):
        if value.get("ns") == "cfg_cam" and str(value.get("k", "")).lower() in (
            "user",
            "username",
            "password",
            "credentials",
            "credential_profile",
            "cred_profile",
        ):
            return {
                key: "***" if key == "v" else redact_rpc(item)
                for key, item in value.items()
            }
        return {
            key: (
                "***"
                if str(key).lower() in SENSITIVE_FIELDS
                or (
                    str(key).lower() == "command_line"
                    and isinstance(item, str)
                    and re.search(
                        r"(?i)(?:^|[\\/\s\"])l4pin(?:\.exe)?(?:[\"\s]|$)", item
                    )
                )
                else redact_rpc(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_rpc(item) for item in value]
    return value
