"""IR-cut RPC extension; independent of frozen camera/media descriptors."""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

from core.camera.contract import bounded_json
from core.config import settings

REVISION = "siplite-ircut/1.0.0"
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
MAC = re.compile(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\Z")
HEX = re.compile(r"[0-9a-f]{64}\Z")


def _match(pattern: re.Pattern, value: Any) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def validate_ircut(method: int, payload: Any) -> dict:
    bounded_json(payload, 8192)
    if not isinstance(payload, dict) or set(payload) != {"dt"}:
        raise ValueError("invalid_ircut_payload")
    dt = payload["dt"]
    if not isinstance(dt, list) or len(dt) != 1 or not isinstance(dt[0], dict):
        raise ValueError("invalid_ircut_payload")
    item = dt[0]
    action = item.get("action")
    if (
        method not in (168, 169)
        or action not in {"inspect", "start", "status", "cancel", "apply", "recover"}
        or (method == 169 and action == "apply")
    ):
        raise ValueError("invalid_ircut_action")
    allowed = {"ircut_revision", "camera_mac", "camera_id", "action", "timeout_ms"}
    required = {"ircut_revision", "camera_mac", "action"}
    if action != "inspect":
        allowed.add("session_id")
        required.add("session_id")
    if action in ("start", "apply"):
        allowed |= {"boot_id", "expected_revision", "allow_disruptive"}
        required |= {"boot_id", "expected_revision", "allow_disruptive"}
    if action == "start":
        allowed.add("budget_ms")
        if method == 168:
            allowed.add("pairs")
    if not required <= set(item) <= allowed or item.get("ircut_revision") != REVISION:
        raise ValueError("invalid_ircut_fields")
    camera = item["camera_mac"]
    if (
        not _match(MAC, camera)
        or int(camera[:2], 16) & 1
        or camera == "00:00:00:00:00:00"
    ):
        raise ValueError("invalid_ircut_camera")
    if item.get("camera_id", "cam:ip000001") != "cam:ip000001":
        raise ValueError("invalid_ircut_camera")
    for key in ("session_id", "boot_id"):
        if key in item and not _match(UUID, item[key]):
            raise ValueError("invalid_ircut_uuid")
    if "expected_revision" in item and not _match(HEX, item["expected_revision"]):
        raise ValueError("invalid_ircut_revision")
    if "allow_disruptive" in item and item["allow_disruptive"] is not True:
        raise ValueError("ircut_confirmation_required")
    for key, high in (("timeout_ms", 30000), ("budget_ms", 2147483647)):
        if key in item and (
            type(item[key]) is not int or not 1000 <= item[key] <= high
        ):
            raise ValueError("invalid_ircut_budget")
    if "pairs" in item:
        pairs = item["pairs"]
        seen = set()
        if not isinstance(pairs, list) or not pairs:
            raise ValueError("invalid_ircut_pairs")
        for pair in pairs:
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or any(
                    type(pin) is not int or not 0 <= pin <= 2147483647 for pin in pair
                )
                or pair[0] == pair[1]
            ):
                raise ValueError("invalid_ircut_pair")
            key = tuple(sorted(pair))
            if key in seen:
                raise ValueError("duplicate_ircut_pair")
            seen.add(key)
    return payload


def require_ircut(method: int, item: dict, observation: dict | None) -> None:
    if (
        not isinstance(observation, dict)
        or observation.get("ircut_revision") != REVISION
    ):
        raise HTTPException(409, "ircut_contract_not_negotiated")
    if method not in observation.get("methods", []):
        raise HTTPException(409, "ircut_method_unsupported")
    action = item["action"]
    if action == "inspect":
        return
    if observation.get("camera_mac") != item["camera_mac"]:
        raise HTTPException(409, "ircut_camera_conflict")
    if action in ("status", "cancel", "recover"):
        if observation.get("session_id") != item["session_id"]:
            raise HTTPException(409, "ircut_session_conflict")
        # Cleanup remains available after a rollout gate is turned off.
        return
    if not settings.camera.writers_enabled:
        raise HTTPException(409, "camera_writers_disabled")
    if (
        observation.get("boot_id") != item["boot_id"]
        or observation.get("revision") != item["expected_revision"]
    ):
        raise HTTPException(409, "ircut_revision_conflict")
