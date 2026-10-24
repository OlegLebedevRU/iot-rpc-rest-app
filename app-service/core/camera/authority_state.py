"""Validated JSON authority upgrade; no defaults repair a lost fence/counter."""

from __future__ import annotations

import copy
import json
from datetime import datetime
from functools import lru_cache
from uuid import UUID

from core.camera.contract import bounded_json, validate_definition
from core.camera.native_contract import SELECTED, validate11
from core.camera.runtime_state import initial_state
from core.camera.runtime_wire import MAX_COUNTER, digest, validate, validator

OPTIONAL = {"epoch", "last_tick", "completed", "completed_hello"}


def uuid4(value) -> bool:
    try:
        return (
            isinstance(value, str)
            and str(UUID(value)) == value
            and UUID(value).version == 4
        )
    except ValueError, TypeError, AttributeError:
        return False


def number(value, maximum=MAX_COUNTER) -> bool:
    return type(value) is int and 0 <= value <= maximum


@lru_cache(maxsize=256)
def checked_wire(raw: str) -> None:
    validate(json.loads(raw))


def wire(value) -> None:
    checked_wire(json.dumps(value, sort_keys=True, separators=(",", ":")))


@lru_cache(maxsize=64)
def checked_configuration(raw: str) -> None:
    value = json.loads(raw)
    if set(value) not in (
        {"descriptor", "binding"},
        {"descriptor", "binding", "selection", "observation"},
    ):
        raise ValueError("configuration_keys")
    descriptor, binding = value["descriptor"], value["binding"]
    if value.get("selection") is not None:
        if value["selection"] != SELECTED:
            raise ValueError("configuration_selection")
        validate11("camera_descriptor", descriptor)
        observation = validate11("camera_observation", value["observation"])
        if (
            descriptor["geometry_generation"] != observation["geometry_generation"]
            or descriptor["source_id"] != observation["source_id"]
            or descriptor["tracks"][0] != observation["actual_track"]
        ):
            raise ValueError("configuration_observation")
    else:
        validate_definition("hevc.schema.json", "camera_descriptor", descriptor)
    expected = {
        "source_id",
        "physical_camera_mac",
        "path_generation",
        "codec",
        "descriptor_sha256",
    }
    if set(binding) != expected:
        raise ValueError("configuration_binding_keys")
    schema = validator(False).schema
    if (
        not validator(False)
        .evolve(schema={"$defs": schema["$defs"], "$ref": "#/$defs/binding"})
        .is_valid({**binding, "boot_id": "00000000-0000-4000-8000-000000000001"})
    ):
        raise ValueError("configuration_binding")
    if (
        binding["source_id"] != descriptor["source_id"]
        or binding["codec"] != descriptor["tracks"][0]["codec"]
        or binding["descriptor_sha256"] != digest(descriptor)
        or not binding["path_generation"].endswith(
            "/" + str(descriptor["geometry_generation"])
        )
    ):
        raise ValueError("configuration_digest")


def load_state(value: dict) -> dict:
    """Upgrade only a complete v1 record. Preserve every authority value verbatim."""
    try:
        bounded_json(value, 8 * 1024 * 1024, 20)
        required = set(initial_state())
        if (
            not isinstance(value, dict)
            or not required <= value.keys()
            or set(value) - required - OPTIONAL
        ):
            raise ValueError("keys")
        if type(value["version"]) is not int or value["version"] not in (1, 2):
            raise ValueError("version")
        if (
            not number(value["generation"])
            or not number(value["counter"])
            or type(value["enrolled"]) is not bool
        ):
            raise ValueError("counter")
        if value["boot"] is not None and not uuid4(value["boot"]):
            raise ValueError("boot")
        retired = value["retired"]
        if (
            not isinstance(retired, list)
            or len(retired) > 65536
            or len(set(retired)) != len(retired)
            or any(not uuid4(v) for v in retired)
            or value["boot"] in retired
        ):
            raise ValueError("retired")
        for cache, order in (
            ("commands", "command_order"),
            ("results", "result_order"),
            ("hellos", "hello_order"),
        ):
            if (
                not isinstance(value[cache], dict)
                or not isinstance(value[order], list)
                or len(value[cache]) > 64
                or len(value[order]) != len(value[cache])
                or set(value[cache]) != set(value[order])
                or any(not uuid4(k) for k in value[cache])
            ):
                raise ValueError("cache")
        if not isinstance(value["jobs"], list) or len(value["jobs"]) > 64:
            raise ValueError("jobs")
        for job in value["jobs"]:
            if (
                set(job) != {"id", "action", "value", "until"}
                or not uuid4(job["id"])
                or not isinstance(job["value"], dict)
            ):
                raise ValueError("job")
            datetime.fromisoformat(job["until"])
        if value["configured"] is not None:
            checked_configuration(
                json.dumps(value["configured"], sort_keys=True, separators=(",", ":"))
            )
        if value["enrolled"] and (
            value["configured"] is None
            or value["boot"] is None
            or not uuid4(value.get("epoch"))
        ):
            raise ValueError("enrolled")
        if "epoch" in value and not uuid4(value["epoch"]):
            raise ValueError("epoch")
        if "last_tick" in value and not number(value["last_tick"], (1 << 64) - 1):
            raise ValueError("tick")
        for name in ("pending", "ready", "active", "completed"):
            item = value.get(name)
            if item is None:
                continue
            if not isinstance(item, dict) or not number(
                item["deadline"], (1 << 64) - 1
            ):
                raise ValueError("deadline")
            for key in {
                "pending": ("hello", "offer"),
                "ready": ("query",),
                "active": ("start",),
                "completed": ("proof", "commit"),
            }[name]:
                wire(item[key])
            if name == "active" and (
                not number(item["seq"])
                or item["seq"] < 1
                or item["start"]["admission_seq"] > value["counter"]
            ):
                raise ValueError("active_counter")
            if name in ("ready", "active"):
                command = item["query" if name == "ready" else "start"]
                if (
                    not value["enrolled"]
                    or command["issuer_epoch"] != value["epoch"]
                    or command["binding"]
                    != {**value["configured"]["binding"], "boot_id": value["boot"]}
                    or command["admission_seq"] > value["counter"]
                ):
                    raise ValueError("live_fence")
            if name == "ready" and any(
                type(item[k]) is not bool for k in ("accepted", "consumed")
            ):
                raise ValueError("readiness_flags")
            if name == "completed":
                proof, commit = item["proof"], item["commit"]
                if (
                    any(
                        commit[k] != v
                        for k, v in proof.items()
                        if k not in ("type", "admission_floor")
                    )
                    or commit["admission_floor"]
                    < max(proof["admission_floor"], proof["admission_high_water"])
                    or (
                        commit["boot_id"] == value["boot"]
                        and commit["admission_floor"] > value["counter"]
                    )
                ):
                    raise ValueError("completed_floor")
        for receipt in value["commands"].values():
            wire(receipt["message"])
        if not isinstance(value["outbox"], list) or len(value["outbox"]) > 64:
            raise ValueError("outbox")
        for entry in value["outbox"]:
            if (
                set(entry) != {"message", "deadline", "held"}
                or not number(entry["deadline"], (1 << 64) - 1)
                or type(entry["held"]) is not bool
            ):
                raise ValueError("outbox_entry")
            wire(entry["message"])
        if (
            value["version"] == 1
            and value["configured"] is not None
            and value["configured"].get("selection") is not None
        ):
            raise ValueError("v1_selection")
        result = copy.deepcopy(value)
        result["version"] = 2
        return result
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise ValueError("camera_authority_corrupt") from exc
