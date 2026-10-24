"""Fenced per-SN actor with durable inbox/outbox, shared by all app workers."""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import time
from datetime import timedelta
from uuid import UUID, uuid4

from core.camera.contract import bounded_json
from core.camera.runtime_state import CameraMachine, increase
from core.camera.runtime_store import AuthorityStore
from core.camera.runtime_wire import CameraRuntimeCommand, digest
from core.config import settings

log = logging.getLogger(__name__)


class CameraRuntime:
    def __init__(
        self, store=None, send=None, authority=None, monotonic=None, wall=None
    ):
        self.store = store or AuthorityStore()
        self.send = send or self.publish
        self.authority = authority or self.check_lease
        self.monotonic = monotonic or (lambda: time.monotonic_ns() // 1000000)
        self.wall = wall or (lambda: time.time_ns() // 1000000)
        self._pid = None
        self._owner = ""
        self.clocks = {}

    @property
    def owner(self) -> str:
        # Gunicorn preload must not clone a process identity/clock into children.
        if self._pid != os.getpid():
            self._pid = os.getpid()
            self._owner = str(uuid4())
            self.clocks = {}
        return self._owner

    async def submit(
        self, sn: str, action: str, value: dict, timeout: float = 10
    ) -> dict | bool:
        if not settings.camera.monotonic_runtime_enabled:
            raise ValueError("camera_monotonic_runtime_disabled")
        bounded_json(value, 32768, 12)
        if value.get("sn", sn) != sn:
            raise ValueError("camera_runtime_sn_mismatch")
        job_id = str(uuid4())
        async with self.store.locked(sn) as (row, now):
            if len(row.state["jobs"]) >= 64:
                raise ValueError("camera_inbox_busy")
            row.state["jobs"].append(
                {
                    "id": job_id,
                    "action": action,
                    "value": copy.deepcopy(value),
                    "until": (now + timedelta(seconds=timeout)).isoformat(),
                }
            )
        began = self.monotonic()
        deadline = began + int(timeout * 1000)
        while self.monotonic() < deadline:
            if self.monotonic() < began:
                raise ValueError("camera_issuer_clock_regressed")
            await self.pump(sn)
            result = (await self.store.get(sn))["results"].get(job_id)
            if result is not None:
                if "error" in result:
                    raise ValueError(result["error"])
                return result["value"]
            await asyncio.sleep(0.025)
        raise TimeoutError("camera_runtime_job_timeout")

    async def pump(self, sn: str) -> None:
        # All workers may enqueue. Exactly one owner interprets local monotonic
        # fields. Takeover invalidates these fields before reading any requests.
        owner = self.owner
        async with self.store.locked(sn) as (row, db_now):
            state = row.state
            if row.owner != owner or sn not in self.clocks:
                if row.owner_until is not None and row.owner_until > db_now:
                    return
                state["generation"] = increase(state["generation"])
                state.update(
                    epoch=str(uuid4()),
                    enrolled=False,
                    pending=None,
                    ready=None,
                    active=None,
                    outbox=[],
                    commands={},
                    command_order=[],
                    completed=None,
                    completed_hello=None,
                )
                row.owner = owner
                self.clocks[sn] = (self.monotonic(), self.wall(), state["epoch"])
                state["last_tick"] = self.clocks[sn][0]
            origin = self.clocks.get(sn)
            if not origin or origin[2] != state["epoch"]:
                raise ValueError("camera_issuer_clock_lost")
            tick = self.monotonic()
            if tick < origin[0] or tick < state.get("last_tick", origin[0]):
                # Do not publish or rebase on a regressed clock.
                state.update(
                    enrolled=False, pending=None, ready=None, active=None, outbox=[]
                )
                row.owner_until = db_now
                self.clocks.pop(sn, None)
                return
            state["last_tick"] = tick
            row.owner_until = db_now + timedelta(seconds=10)
            CameraMachine(state, tick, origin[1] + tick - origin[0]).expire()
            from datetime import datetime

            for _ in range(min(len(state["jobs"]), 16)):
                job = state["jobs"].pop(0)
                try:
                    if datetime.fromisoformat(job["until"]) <= db_now:
                        raise ValueError("camera_job_expired")
                    value = copy.deepcopy(job["value"])
                    if job["action"] in ("start", "renew"):
                        value["budget_ms"] = await self.authority(sn, value)
                    updated = copy.deepcopy(state)
                    result = CameraMachine(
                        updated, tick, origin[1] + tick - origin[0]
                    ).apply(job["action"], value)
                    state = row.state = updated
                    state["results"][job["id"]] = {"value": result}
                except ValueError as exc:
                    state["results"][job["id"]] = {"error": str(exc)}
                state["result_order"].append(job["id"])
                while len(state["result_order"]) > 64:
                    del state["results"][state["result_order"].pop(0)]
        # Previous transaction has durably committed every outbound payload.
        await self.flush(sn)

    async def flush(self, sn: str) -> None:
        async with self.store.locked(sn) as (row, db_now):
            if (
                row.owner != self.owner
                or row.owner_until is None
                or row.owner_until <= db_now
            ):
                return
            origin = self.clocks.get(sn)
            if not origin or origin[2] != row.state["epoch"]:
                return
            tick = self.monotonic()
            if tick < row.state["last_tick"]:
                return
            pending = []
            for entry in row.state["outbox"]:
                tick = self.monotonic()
                remaining = entry["deadline"] - tick
                if remaining <= 0:
                    continue
                if entry["held"]:
                    pending.append(entry)
                    continue
                message = entry["message"]
                if message["issuer_epoch"] != row.state["epoch"]:
                    continue
                if message["type"] in ("stream_start", "lease_renew"):
                    try:
                        lease_budget = await self.authority(sn, message)
                        remaining = entry["deadline"] - self.monotonic()
                        if remaining <= 0 or lease_budget < remaining:
                            # A shorter transport TTL cannot repair a stale wire
                            # lease budget. Never publish that payload after shrink.
                            continue
                    except ValueError:
                        continue
                try:
                    # Hold the durable fence lock through broker confirmation.
                    # No successor owner can claim/advance generation meanwhile.
                    await asyncio.wait_for(self.send(sn, message, remaining), 2)
                except Exception:  # noqa: BLE001
                    # Ambiguous delivery retries identical bytes/ID, still fenced.
                    pending.append(entry)
            row.state["outbox"] = pending

    async def command(
        self, action: str, epoch, lease=None, readiness_nonce: str | None = None
    ) -> CameraRuntimeCommand:
        identity = epoch.identity
        value = {k: identity[k] for k in ("sn", "lease_id", "stream_instance_id")}
        if action == "start":
            value.update(
                command_id=epoch.start["operation_id"],
                descriptor_sha256=digest(epoch.start["descriptor"]),
                readiness_nonce=readiness_nonce,
            )
        if lease is not None:
            value.update(
                owner_user_id=lease.owner_user_id,
                owner_session_id=lease.owner_session_id,
            )
        result = await self.submit(identity["sn"], action, value)
        return CameraRuntimeCommand(result)

    async def release(self, command: CameraRuntimeCommand) -> None:
        await self.submit(
            command.root["sn"], "release", {"command_id": str(command.command_id)}
        )

    async def accept_ack(self, sn: str, value: dict) -> bool:
        try:
            if value["command_id"] not in (await self.store.get(sn))["commands"]:
                return False
            safe = {
                k: value[k]
                for k in (
                    "command_id",
                    "sn",
                    "lease_id",
                    "stream_instance_id",
                    "result",
                )
                if k in value
            }
            return bool(await self.submit(sn, "ack", safe))
        except ValueError:
            return False

    async def wait_ack(self, command: CameraRuntimeCommand, timeout: float = 15):
        from core.remote_input.pending import PendingResult

        began = self.monotonic()
        deadline = began + int(timeout * 1000)
        while self.monotonic() < deadline:
            if self.monotonic() < began:
                raise ValueError("camera_issuer_clock_regressed")
            state = await self.store.get(command.root["sn"])
            receipt = state["commands"].get(str(command.command_id))
            if receipt is None:
                raise ValueError("camera_command_retired")
            ack = receipt.get("ack")
            if ack:
                return PendingResult(
                    result=ack.get("result", "nack"),
                    stream_instance_id=UUID(ack["stream_instance_id"]),
                    expires_at_ms=command.expires_at_ms,
                )
            await asyncio.sleep(0.025)
        raise TimeoutError("camera_ack_timeout")

    @staticmethod
    async def check_lease(sn: str, value: dict) -> int:
        from core.redis_helper import redis_helper
        from core.remote_input.leases import lease_registry

        lease = await lease_registry.get(UUID(value["lease_id"]))
        if (
            not lease
            or not lease.is_active()
            or lease.sn != sn
            or lease.scope != "stream"
        ):
            raise ValueError("camera_lease_invalid")
        if (
            lease.stream_instance_id is not None
            and str(lease.stream_instance_id) != value["stream_instance_id"]
        ):
            raise ValueError("camera_lease_invalid")
        for key in ("owner_user_id", "owner_session_id"):
            if key in value and value[key] != getattr(lease, key):
                raise ValueError("camera_lease_owner_changed")
        # The active Redis key has the actual lease TTL (the hash has +30s retention).
        # UTC movement cannot enlarge the exported issuer-coordinate budget.
        client = redis_helper.get_client()
        key = f"l4d:lease:active:{sn}"
        before = time.monotonic_ns() // 1000000
        async with client.pipeline(transaction=True) as pipe:
            pipe.get(key)
            pipe.pttl(key)
            active, remaining = await pipe.execute()
        remaining -= time.monotonic_ns() // 1000000 - before
        if active != value["lease_id"] or remaining <= 0:
            raise ValueError("camera_lease_invalid")
        return min(60000, remaining)

    @staticmethod
    async def publish(sn: str, message: dict, ttl_ms: int) -> None:
        from core.topologys.declare import topic_publisher

        correlation = message.get(
            "command_id", message.get("enrollment_id", message.get("readiness_nonce"))
        )
        await topic_publisher.publish(
            routing_key=f"{settings.rmq.prefix_srv}.{sn}.{settings.rmq.suffix_control}",
            message=message,
            correlation_id=UUID(correlation),
            expiration=ttl_ms,
            headers={"correlationData": correlation, "ctl_type": message["type"]},
        )


camera_runtime = CameraRuntime()


async def camera_runtime_loop() -> None:
    while True:
        try:
            if settings.camera.monotonic_runtime_enabled:
                for sn in await camera_runtime.store.candidates():
                    try:
                        await camera_runtime.pump(sn)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        log.exception("Camera runtime authority failed: sn=%s", sn)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Camera runtime pump failed")
        await asyncio.sleep(0.1)
