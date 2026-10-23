"""Production validation against the accepted, immutable camera package."""

from __future__ import annotations

import base64
import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker, ValidationError, validators

REVISION = "siplite-camera/1.0.0"
PACKAGE = Path(__file__).resolve().parents[3] / "contracts" / "siplite-camera-v1"


def strict_const(validator, expected, instance, schema):
    if type(instance) is not type(expected) or instance != expected:
        yield ValidationError("constant value/type mismatch")


def strict_enum(validator, expected, instance, schema):
    if not any(
        type(instance) is type(value) and instance == value for value in expected
    ):
        yield ValidationError("enumeration value/type mismatch")


StrictValidator = validators.extend(
    Draft202012Validator,
    validators={"const": strict_const, "enum": strict_enum},
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine(
        "integer", lambda checker, value: type(value) is int
    ),
)


@lru_cache
def schema_validator(filename: str, definition: str):
    schema = json.loads((PACKAGE / filename).read_text(encoding="utf-8"))
    return StrictValidator(
        {"$defs": schema["$defs"], "$ref": f"#/$defs/{definition}"},
        format_checker=FormatChecker(),
    )


def bounded_json(value: Any, limit: int, depth: int = 12) -> None:
    try:
        raw = json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
        if len(raw.encode("utf-8")) > limit:
            raise ValueError

        def visit(item, level):
            if level > depth:
                raise ValueError
            if isinstance(item, dict):
                for key, child in item.items():
                    if not isinstance(key, str):
                        raise ValueError
                    visit(child, level + 1)
            elif isinstance(item, list):
                for child in item:
                    visit(child, level + 1)

        visit(value, 0)
    except ValueError, TypeError, RecursionError, UnicodeError:
        raise ValueError("invalid_camera_json_bounds") from None


def validate_definition(filename: str, definition: str, value: Any, limit=32768):
    bounded_json(value, limit)
    if not schema_validator(filename, definition).is_valid(value):
        # jsonschema errors include offending values, including credential material.
        raise ValueError("invalid_camera_payload")
    return copy.deepcopy(value)


def validate_rpc(method_code: int, payload: Any) -> dict:
    if type(method_code) is not int or method_code not in range(160, 168):
        raise ValueError("unknown_camera_method")
    result = validate_definition(
        "camera-rpc.schema.json", f"rpc{method_code}", payload, 8192
    )
    item = result["dt"][0]
    if "operation_id" in item and UUID(item["operation_id"]).int == 0:
        raise ValueError("camera_operation_id_reserved")
    item.setdefault("camera_id", "cam:ip000001")
    item.setdefault("timeout_ms", {160: 20000, 164: 10000}.get(method_code, 30000))
    if method_code in (161, 162, 163, 164):
        item.setdefault("allow_disruptive", False)
        item.setdefault("dry_run", False)
    envelope = item.get("sealed_credentials")
    if envelope is not None:
        if envelope["operation_id"] != item["operation_id"]:
            raise ValueError("credential_operation_mismatch")
        for field, sizes in (
            ("wrapped_key", (256, 384, 512)),
            ("nonce", (12,)),
            ("tag", (16,)),
            ("ciphertext", range(1, 769)),
        ):
            try:
                decoded = base64.b64decode(envelope[field], validate=True)
                if (
                    len(decoded) not in sizes
                    or base64.b64encode(decoded).decode("ascii") != envelope[field]
                ):
                    raise ValueError
            except ValueError, TypeError:
                raise ValueError("invalid_credential_encoding") from None
    return result
