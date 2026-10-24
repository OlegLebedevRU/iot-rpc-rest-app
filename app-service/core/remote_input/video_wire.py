"""Strict CTL v2 validation: immutable G0 plus inventory source selection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, model_validator

SCHEMA = json.loads(Path(__file__).with_name("video.schema.json").read_text())
# Source-selection extension; keep the frozen G0 schema file byte-for-byte.
SCHEMA["$defs"]["inventory_get"] = json.loads(
    Path(__file__).with_name("video_inventory_memory.schema.json").read_text()
)
SCHEMA["$defs"]["capabilities"] = json.loads(
    Path(__file__).with_name("video_capabilities_memory.schema.json").read_text()
)
DEFINITIONS = {
    "Descriptor": "descriptor",
    "Descriptor1": "descriptor",
    "Capabilities": "capabilities",
    "InventoryGet": "inventory_get",
    "CapabilitiesAck": "capabilities_ack",
    "Start": "start",
    "Ready": "ready",
    "Error": "error",
    "Stop": "stop",
    "LeaseRenew": "lease_renew",
    "StartAck": "start_ack",
    "Nack": "nack",
}
VALIDATORS = {
    name: Draft202012Validator(
        {"$ref": f"#/$defs/{definition}", "$defs": SCHEMA["$defs"]},
        format_checker=FormatChecker(),
    )
    for name, definition in DEFINITIONS.items()
}


class WireModel(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def validate_wire(cls, value: Any) -> Any:
        if cls.__name__ in VALIDATORS and isinstance(value, dict):
            errors = list(VALIDATORS[cls.__name__].iter_errors(value))
            if errors:
                raise ValueError(errors[0].message)
        return value


def load_object(
    payload: bytes | str | dict[str, Any], limit: int = 32768
) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    if isinstance(payload, dict):
        raw = json.dumps(payload).encode("utf-8")
    else:
        raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    if len(raw) > limit:
        raise ValueError("CTL v2 exceeds 32768 bytes")
    result = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(result, dict):
        raise TypeError("CTL object required")
    return result
