"""Camera-only media deadline export, anchored once per Redis publisher lease."""

from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from uuid import UUID, uuid4

from redis.exceptions import WatchError

from core.remote_input.leases import _dict_to_lease, _lease_to_dict


@lru_cache(maxsize=1)
def kernel_boot() -> str:
    try:
        return str(UUID(Path("/proc/sys/kernel/random/boot_id").read_text().strip()))
    except OSError, ValueError:
        raise ValueError("camera_media_clock_unavailable") from None


@dataclass(frozen=True)
class MediaLease:
    media_lease_expires_at: int
    media_remaining_ms: int
    media_clock_id: str
    coordinate_now_ms: int
    sampled_mono_ms: int | None = None

    def public(self) -> dict:
        return {
            "media_lease_expires_at": self.media_lease_expires_at,
            "media_remaining_ms": self.media_remaining_ms,
            "media_clock_id": self.media_clock_id,
        }


class CameraMediaClock:
    def __init__(self, client=None, monotonic=None, wall=None, boot=None):
        self._client = client
        self.monotonic = monotonic or (lambda: time.monotonic_ns() // 1000000)
        self.wall = wall or (lambda: time.time_ns() // 1000000)
        self.boot = boot or kernel_boot

    @property
    def client(self):
        if self._client is not None:
            return self._client
        from core.redis_helper import redis_helper

        return redis_helper.get_client()

    @staticmethod
    def scoped(raw: dict) -> bool:
        return raw.get("camera_media_clock_initialized") == "1" or (
            raw.get("stream_contract_version") == "3"
            and raw.get("stream_mode") == "usb-camera"
            and raw.get("selected_camera_id") == "cam:ip000001"
        )

    def anchor(self, raw: dict, now: int) -> dict:
        try:
            a = json.loads(raw["camera_media_clock"])
            if not self.scoped(raw) or set(a) != {
                "clock_id",
                "kernel_boot",
                "sn",
                "lease_id",
                "owner_user_id",
                "owner_session_id",
                "origin_mono_ms",
                "origin_utc_ms",
                "last_mono_ms",
                "deadline_mono_ms",
            }:
                raise ValueError
            if (
                a["kernel_boot"] != self.boot()
                or a["sn"] != raw["sn"]
                or a["lease_id"] != raw["lease_id"]
                or a["owner_user_id"] != raw.get("owner_user_id")
                or a["owner_session_id"] != raw.get("owner_session_id", "")
                or str(UUID(a["clock_id"])) != a["clock_id"]
                or UUID(a["clock_id"]).version != 4
                or any(
                    type(a[k]) is not int or not 0 <= a[k] <= (1 << 53) - 1
                    for k in (
                        "origin_mono_ms",
                        "origin_utc_ms",
                        "last_mono_ms",
                        "deadline_mono_ms",
                    )
                )
                or not a["origin_mono_ms"]
                <= a["last_mono_ms"]
                <= now
                < a["deadline_mono_ms"]
            ):
                raise ValueError
            return a
        except KeyError, TypeError, ValueError:
            raise ValueError("camera_media_clock_lost_or_expired") from None

    async def read(
        self, lease, *, initialize: bool = False, renew_sec: int | None = None
    ) -> tuple[MediaLease, object]:
        key = f"l4d:lease:{lease.lease_id}"
        active = f"l4d:lease:active:{lease.sn}"
        for _ in range(5):
            async with self.client.pipeline(transaction=True) as pipe:
                try:
                    await pipe.watch(key, active)
                    before = self.monotonic()
                    raw = await pipe.hgetall(key)
                    current = await pipe.get(active)
                    ttl = await pipe.pttl(active)
                    now = self.monotonic()
                    remaining = min(60000, ttl - (now - before))
                    if (
                        not raw
                        or current != str(lease.lease_id)
                        or remaining <= 0
                        or now < before
                        or lease.scope != "stream"
                        or raw.get("sn") != lease.sn
                        or raw.get("revoked_reason")
                        or raw.get("scope") != "stream"
                        or raw.get("owner_user_id") != lease.owner_user_id
                        or raw.get("owner_session_id", "") != lease.owner_session_id
                    ):
                        raise ValueError("camera_media_lease_invalid")
                    if not self.scoped(raw):
                        if (
                            not initialize
                            or raw.get("stream_instance_id")
                            or "camera_media_clock" in raw
                        ):
                            raise ValueError("camera_media_clock_lost_or_expired")
                        utc = self.wall()
                        if (
                            type(utc) is not int
                            or not 1700000000000 <= utc <= 5000000000000
                        ):
                            raise ValueError("camera_media_clock_unavailable")
                        sampled = self.monotonic()
                        if sampled < now:
                            raise ValueError("camera_media_clock_lost_or_expired")
                        remaining -= sampled - now
                        now = sampled
                        if remaining <= 0 or now < before:
                            raise ValueError("camera_media_lease_invalid")
                        a = {
                            "clock_id": str(uuid4()),
                            "kernel_boot": self.boot(),
                            "sn": lease.sn,
                            "lease_id": str(lease.lease_id),
                            "owner_user_id": lease.owner_user_id,
                            "owner_session_id": lease.owner_session_id,
                            "origin_mono_ms": now,
                            "origin_utc_ms": utc,
                            "last_mono_ms": now,
                            "deadline_mono_ms": now + remaining,
                        }
                    else:
                        a = self.anchor(raw, now)
                        remaining = min(remaining, a["deadline_mono_ms"] - now)
                    original = copy.deepcopy(a)
                    a["last_mono_ms"] = now
                    renewed = _dict_to_lease(raw)
                    if renew_sec is not None:
                        if type(renew_sec) is not int or not 1 <= renew_sec <= 60:
                            raise ValueError("camera_media_lease_budget")
                        # A real server keepalive extends Redis authority. Reading
                        # or replaying an export never restarts this budget.
                        remaining = renew_sec * 1000
                        a["deadline_mono_ms"] = now + remaining
                        renewed.last_keepalive_at = datetime.fromtimestamp(
                            self.wall() / 1000, UTC
                        )
                        renewed.expires_at = renewed.last_keepalive_at + timedelta(
                            seconds=renew_sec
                        )
                        renewed.ttl_sec = renew_sec
                    coordinate = a["origin_utc_ms"] + now - a["origin_mono_ms"]
                    snapshot = MediaLease(
                        (coordinate + remaining) // 1000,
                        remaining,
                        a["clock_id"],
                        coordinate,
                        now,
                    )
                    if renew_sec is None and self.scoped(raw) and a == original:
                        return snapshot, renewed
                    pipe.multi()
                    if renew_sec is not None:
                        pipe.hset(key, mapping=_lease_to_dict(renewed))
                        pipe.expire(key, renew_sec + 30)
                        pipe.expire(active, renew_sec)
                    pipe.hset(
                        key,
                        mapping={
                            "camera_media_clock_initialized": "1",
                            "camera_media_clock": json.dumps(a, separators=(",", ":")),
                        },
                    )
                    await pipe.execute()
                    return snapshot, renewed
                except WatchError:
                    continue
        raise ValueError("camera_media_lease_busy")

    async def export(self, lease, *, initialize: bool = False) -> MediaLease:
        return (await self.read(lease, initialize=initialize))[0]

    async def touch(self, lease, seconds: int):
        return (await self.read(lease, renew_sec=seconds))[1]

    async def save_stream(self, lease, expected_stream) -> bool:
        key = f"l4d:lease:{lease.lease_id}"
        active = f"l4d:lease:active:{lease.sn}"
        for _ in range(5):
            async with self.client.pipeline(transaction=True) as pipe:
                try:
                    await pipe.watch(key, active)
                    raw = await pipe.hgetall(key)
                    if (
                        not raw
                        or await pipe.get(active) != str(lease.lease_id)
                        or await pipe.pttl(active) <= 0
                    ):
                        return False
                    self.anchor(raw, self.monotonic())
                    current = raw.get("stream_instance_id") or None
                    if current != (str(expected_stream) if expected_stream else None):
                        return False
                    values = _lease_to_dict(lease)
                    names = (
                        "stream_instance_id",
                        "stream_mode",
                        "stream_state",
                        "stream_profile",
                        "stream_contract_version",
                        "selected_camera_id",
                    )
                    pipe.multi()
                    pipe.hset(key, mapping={n: values[n] for n in names})
                    await pipe.execute()
                    return True
                except WatchError:
                    continue
        return False

    async def publisher_lease(self, service, identity: dict, pipe):
        key = f"l4d:lease:{identity['lease_id']}"
        active = f"l4d:lease:active:{identity['sn']}"
        await pipe.watch(key, active)
        raw = await pipe.hgetall(key)
        if (
            not raw
            or await pipe.get(active) != identity["lease_id"]
            or await pipe.pttl(active) <= 0
            or raw.get("revoked_reason")
            or raw.get("sn") != identity["sn"]
            or raw.get("lease_id") != identity["lease_id"]
            or raw.get("scope") != "stream"
        ):
            return None
        try:
            self.anchor(raw, self.monotonic())
        except ValueError:
            return None
        return _dict_to_lease(raw)


camera_media_clock = CameraMediaClock()
