"""Durable camera state transitions, executed only by a fenced issuer owner."""

from __future__ import annotations

import copy
from uuid import uuid4

from core.camera.native_contract import (
    ENROLLMENT02,
    ENROLLMENT03,
    ENROLLMENT04,
    ENROLLMENT05,
    MEDIA3,
    SELECTED,
    SELECTED3,
    SELECTED4,
    SELECTED5,
)
from core.camera.runtime_wire import (
    ADMISSION,
    MAX_COUNTER,
    digest,
    validate,
)


def increase(number: int) -> int:
    if type(number) is not int or not 0 <= number < MAX_COUNTER:
        raise ValueError("camera_counter_exhausted")
    return number + 1


def initial_state() -> dict:
    return {
        "version": 2,
        "generation": 0,
        "counter": 0,
        "boot": None,
        "retired": [],
        "configured": None,
        "enrolled": False,
        "pending": None,
        "ready": None,
        "active": None,
        "outbox": [],
        "commands": {},
        "command_order": [],
        "jobs": [],
        "results": {},
        "result_order": [],
        "hellos": {},
        "hello_order": [],
    }


class CameraMachine:
    def __init__(self, state: dict, now: int, issued: int):
        self.s, self.now, self.issued = state, now, issued

    def expire(self) -> None:
        for key in ("pending", "ready", "active"):
            if self.s[key] and self.now >= self.s[key]["deadline"]:
                self.s[key] = None
                if key == "active":
                    self.s["ready"] = None

    def emit(self, message: dict, deadline: int, held: bool = False) -> dict:
        validate(message)
        outbox = self.s["outbox"]
        if not any(entry["message"] == message for entry in outbox):
            if len(outbox) >= 64:
                raise ValueError("camera_outbox_busy")
            outbox.append(
                {"message": copy.deepcopy(message), "deadline": deadline, "held": held}
            )
        return message

    def binding(self, boot: str) -> dict:
        return {**self.s["configured"]["binding"], "boot_id": boot}

    def apply(self, action: str, value: dict) -> dict | bool:
        self.expire()
        if action == "configure":
            if self.s["active"]:
                raise ValueError("camera_busy_stream")
            if self.s["configured"] != value:
                self.s.update(
                    configured=copy.deepcopy(value),
                    enrolled=False,
                    pending=None,
                    ready=None,
                    outbox=[],
                    completed=None,
                    completed_hello=None,
                )
            return {"configured": True}
        if not self.s["configured"]:
            raise ValueError("camera_binding_not_prepared")
        if action == "incoming":
            return self.incoming(value)
        if action == "retire":
            active = self.s["active"]
            if not active or any(
                value[k] != active["start"][k]
                for k in ("lease_id", "stream_instance_id")
            ):
                return False
            self.s.update(active=None, ready=None, outbox=[])
            return True
        if action == "release":
            for entry in self.s["outbox"]:
                if entry["message"].get("command_id") == value["command_id"]:
                    entry["held"] = False
                    return True
            return value["command_id"] in self.s["commands"]
        if action == "ack":
            receipt = self.s["commands"].get(value["command_id"])
            if (
                not receipt
                or receipt["message"]["issuer_epoch"] != self.s["epoch"]
                or receipt["message"]["binding"] != self.binding(self.s["boot"])
                or any(
                    value.get(k) != receipt["message"].get(k)
                    for k in ("sn", "lease_id", "stream_instance_id")
                )
            ):
                return False
            if receipt.get("ack"):
                return receipt["ack"] == value
            receipt["ack"] = copy.deepcopy(value)
            if (
                self.s["active"]
                and self.s["active"]["start"]["admission_seq"]
                == receipt["message"]["admission_seq"]
                and value.get("result")
                not in ("started", "already_running", "renewed", "accepted", "injected")
            ):
                self.s["active"] = None
                self.s["ready"] = None
                self.s["outbox"] = []
            return True
        if not self.s["enrolled"]:
            raise ValueError("camera_enrollment_required")
        base = {
            "v": 1,
            "camera_admission_revision": ADMISSION,
            "sn": value["sn"],
            "issuer_epoch": self.s["epoch"],
            "binding": self.binding(self.s["boot"]),
        }
        if action == "readiness":
            if self.s["active"] or self.s["ready"] or self.s["pending"]:
                raise ValueError("camera_admission_busy")
            self.s["counter"] = increase(self.s["counter"])
            query = {
                **base,
                "type": "camera_readiness_query",
                "readiness_nonce": str(uuid4()),
                "admission_seq": self.s["counter"],
                "issued_at_ms": self.issued,
                "expires_at_ms": self.issued + 5000,
            }
            self.s["ready"] = {
                "query": query,
                "deadline": self.now + 5000,
                "accepted": False,
                "consumed": False,
            }
            return self.emit(query, self.now + 5000)
        if action == "start":
            ready = self.s["ready"]
            if (
                self.s["active"]
                or self.s["pending"]
                or not ready
                or not ready["accepted"]
                or ready["consumed"]
            ):
                raise ValueError("camera_fresh_readiness_required")
            if value.get("readiness_nonce") != ready["query"]["readiness_nonce"]:
                raise ValueError("camera_readiness_mismatch")
            if value["descriptor_sha256"] != base["binding"]["descriptor_sha256"]:
                raise ValueError("camera_descriptor_changed")
            ttl = value["budget_ms"]
            if type(ttl) is not int or not 0 < ttl <= 60000:
                raise ValueError("camera_lease_budget")
            query = ready["query"]
            command = {
                **base,
                "type": "stream_start",
                "readiness_nonce": query["readiness_nonce"],
                "admission_seq": query["admission_seq"],
                "command_id": value["command_id"],
                "lease_id": value["lease_id"],
                "stream_instance_id": value["stream_instance_id"],
                "command_seq": 1,
                "issued_at_ms": self.issued,
                "expires_at_ms": self.issued + ttl,
                "mode": "usb-camera",
                "source_id": base["binding"]["source_id"],
                "profile": "default",
            }
            ready["consumed"] = True
            self.s["active"] = {"start": command, "seq": 1, "deadline": self.now + ttl}
        elif action in ("renew", "stop"):
            active = self.s["active"]
            if not active or any(
                value[k] != active["start"][k]
                for k in ("lease_id", "stream_instance_id")
            ):
                raise ValueError("camera_stream_not_live")
            start = active["start"]
            ttl = value.get("budget_ms", 5000)
            if type(ttl) is not int or not 0 < ttl <= (
                5000 if action == "stop" else 60000
            ):
                raise ValueError("camera_lease_budget")
            if action == "renew" and self.now + ttl <= active["deadline"]:
                raise ValueError("camera_renewal_not_advancing")
            active["seq"] = increase(active["seq"])
            command = {
                k: v
                for k, v in start.items()
                if k not in ("mode", "source_id", "profile")
            }
            command.update(
                type="lease_renew" if action == "renew" else "stream_stop",
                command_id=str(uuid4()),
                command_seq=active["seq"],
                issued_at_ms=self.issued,
                expires_at_ms=self.issued + ttl,
            )
            if action == "renew":
                command["ttl_sec"] = 60
                active["deadline"] = self.now + ttl
            else:
                self.s["active"] = self.s["ready"] = None
                self.s["outbox"] = []
        else:
            raise ValueError("camera_runtime_action")
        self.s["commands"][command["command_id"]] = {"message": copy.deepcopy(command)}
        for name in ("media_clock_id", "media_lease_expires_at"):
            if name in value:
                self.s["commands"][command["command_id"]][name] = value[name]
        self.s["command_order"].append(command["command_id"])
        while len(self.s["command_order"]) > 64:
            del self.s["commands"][self.s["command_order"].pop(0)]
        return self.emit(command, self.now + ttl, held=True)

    def incoming(self, message: dict) -> bool:
        validate(message)
        kind = message["type"]
        if kind == "camera_enrollment_hello":
            selection = self.s["configured"].get("selection")
            expected_revision = (
                ENROLLMENT05
                if selection == SELECTED5
                else (
                    ENROLLMENT04
                    if selection == SELECTED4
                    else (
                        ENROLLMENT03
                        if selection == SELECTED3
                        else (
                            ENROLLMENT02
                            if selection == SELECTED
                            else "camera-enrollment/0.1.0-proposed"
                        )
                    )
                )
            )
            if message["revision"] != expected_revision:
                return False
            if (
                message["boot_id"] in self.s["retired"]
                or ADMISSION not in message["supported_ctl"]
            ):
                return False
            pending = self.s["pending"]
            if pending:
                if pending["hello"] != message:
                    return False
                self.emit(pending["offer"], pending["deadline"])
                return True
            # A duplicate completed hello never constructs another enrollment.
            if self.s.get("completed_hello") == message:
                completed = self.s.get("completed")
                if completed and self.now < completed["deadline"]:
                    self.emit(completed["commit"], completed["deadline"])
                    return True
                return False
            if message["enrollment_id"] in self.s["hellos"]:
                return False
            counter = self.s["counter"] if message["boot_id"] == self.s["boot"] else 0
            offer = {
                k: message[k] for k in ("revision", "sn", "boot_id", "enrollment_id")
            }
            offer.update(
                type="camera_enrollment_offer",
                ctl_revision=ADMISSION,
                server_challenge=str(uuid4()),
                issuer_generation=self.s["generation"],
                issuer_epoch=self.s["epoch"],
                binding_hash=digest(self.binding(message["boot_id"])),
                admission_floor=max(counter, message["admission_high_water"]),
            )
            if selection in (SELECTED, SELECTED3, SELECTED4, SELECTED5):
                offer.update(
                    camera_contract_revision=(selection["camera_contract_revision"]),
                    cadence_revision=selection["cadence_revision"],
                    descriptor=copy.deepcopy(self.s["configured"]["descriptor"]),
                    binding=self.binding(message["boot_id"]),
                )
            if selection in (SELECTED3, SELECTED4, SELECTED5):
                offer["media_contract_revision"] = MEDIA3
            self.s["pending"] = {
                "hello": copy.deepcopy(message),
                "offer": offer,
                "deadline": self.now + 5000,
            }
            self.s["hellos"][message["enrollment_id"]] = True
            self.s["hello_order"].append(message["enrollment_id"])
            while len(self.s["hello_order"]) > 64:
                del self.s["hellos"][self.s["hello_order"].pop(0)]
            self.emit(offer, self.now + 5000)
            return True
        if kind == "camera_enrollment_proof":
            pending = self.s["pending"]
            if not pending:
                done = self.s.get("completed")
                if done and self.now < done["deadline"] and done["proof"] == message:
                    self.emit(done["commit"], done["deadline"])
                    return True
                return False
            offer = pending["offer"]
            if message["boot_id"] in self.s["retired"] or any(
                message[k] != v for k, v in offer.items() if k != "type"
            ):
                return False
            if message["boot_id"] != self.s["boot"]:
                if len(self.s["retired"]) >= 65536:
                    raise ValueError("camera_retired_boot_capacity")
                if self.s["boot"]:
                    self.s["retired"].append(self.s["boot"])
                self.s["counter"] = 0
            self.s["counter"] = max(
                self.s["counter"],
                offer["admission_floor"],
                message["admission_high_water"],
            )
            commit = {
                **message,
                "type": "camera_enrollment_commit",
                "admission_floor": self.s["counter"],
            }
            self.s.update(
                boot=message["boot_id"],
                enrolled=True,
                completed_hello=pending["hello"],
                active=None,
                ready=None,
                outbox=[],
            )
            self.s["completed"] = {
                "proof": copy.deepcopy(message),
                "commit": commit,
                "deadline": pending["deadline"],
            }
            self.s["pending"] = None
            self.emit(commit, pending["deadline"])
            return True
        ready = self.s["ready"]
        if (
            kind != "camera_readiness_result"
            or not self.s["enrolled"]
            or not ready
            or ready["consumed"]
        ):
            return False
        if any(
            message[k] != v
            for k, v in ready["query"].items()
            if k not in ("type", "issued_at_ms", "expires_at_ms")
        ):
            return False
        ready["accepted"] = True
        return True
