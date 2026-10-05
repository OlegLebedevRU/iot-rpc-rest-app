"""Bounded FM metadata exchange. Redis correlates responses across app workers.

One complete page per message, <= 24 KiB; no partial page can reach the UI.
There are no task retries and no HTTP fallback to the terminal/PB.
"""

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis.exceptions import WatchError

from core.redis_helper import redis_helper
from core.config import settings
from core.remote_input.leases import Lease, lease_registry
from core.topologys.declare import topic_publisher


class Navigation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["list", "stop"] = "list"
    path: str = Field(min_length=3, max_length=1024)
    offset: int = Field(default=0, ge=0, le=1_000_000)


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(
        min_length=1, max_length=255, pattern=r'^[^\\/:*?"<>|\x00-\x1f]+$'
    )
    directory: bool
    size_bytes: int = Field(ge=0)


class Result(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    v: Literal[2]
    command_id: str
    lease_id: str
    state: Literal["completed", "failed"]
    entries: list[Entry] = Field(default_factory=list, max_length=64)
    has_more: bool = False
    error_code: str | None = Field(default=None, max_length=64, pattern=r"^[a-z0-9_]+$")


async def navigate(lease: Lease, body: Navigation) -> dict:
    client = redis_helper.get_client()
    command_id = str(uuid4())
    key = f"l4fm:pending:{command_id}"
    reply = f"{key}:result"
    guard = f"l4fm:{body.action}:{lease.lease_id}"
    if not await client.set(guard, command_id, nx=True, ex=10):
        raise HTTPException(409, detail={"code": "fm_navigation_busy"})
    try:
        await client.set(
            key, json.dumps({"sn": lease.sn, "lease_id": str(lease.lease_id)}), ex=10
        )
        expiry = min(
            int(lease.expires_at.timestamp()), int(datetime.now(UTC).timestamp()) + 7
        )
        if body.action == "stop":
            expiry = int(datetime.now(UTC).timestamp()) + 7
        await topic_publisher.publish(
            routing_key=f"{settings.rmq.prefix_srv}.{lease.sn}.{settings.rmq.suffix_fm_command}",
            message={
                "v": 2,
                "command_id": command_id,
                "lease_id": str(lease.lease_id),
                "action": body.action,
                **(
                    {"path": body.path, "offset": body.offset}
                    if body.action == "list"
                    else {}
                ),
                "expires_at": expiry,
            },
            correlation_id=command_id,
            expiration=timedelta(seconds=7),
            headers={"correlationData": command_id},
        )
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            value = await client.get(reply)
            if value:
                current = await lease_registry.get(lease.lease_id)
                if current is None or (
                    body.action != "stop" and not current.is_active()
                ):
                    raise HTTPException(409, detail={"code": "lease_expired"})
                return json.loads(value)
            await asyncio.sleep(0.1)
        await lease_registry.revoke(lease.lease_id, reason="fm_navigation_timeout")
        raise HTTPException(504, detail={"code": "fm_ack_timeout"})
    except Exception:
        await lease_registry.revoke(lease.lease_id, reason="fm_navigation_failed")
        raise
    finally:
        # Guard lifetime exceeds this request. Compare-delete, never erase a newer owner.
        for _ in range(3):
            try:
                async with client.pipeline(transaction=True) as pipe:
                    await pipe.watch(guard)
                    if await pipe.get(guard) != command_id:
                        break
                    pipe.multi()
                    pipe.delete(guard)
                    await pipe.execute()
                    break
            except WatchError:
                continue  # TTL remains a bound if a new request wins the guard.
        await client.delete(key, reply)


async def accept_result(sn: str, payload: bytes) -> None:
    if not payload or len(payload) > 24576:
        return
    try:
        result = Result.model_validate_json(payload)
        identifier = str(UUID(result.command_id))
        if result.command_id != identifier or result.lease_id != str(
            UUID(result.lease_id)
        ):
            return
        if any(entry.name in (".", "..") for entry in result.entries):
            return
    except ValidationError, ValueError:
        return
    client = redis_helper.get_client()
    key = f"l4fm:pending:{identifier}"
    pending = await client.get(key)
    if pending is None:
        return
    expected = json.loads(pending)
    if expected != {"sn": sn, "lease_id": result.lease_id}:
        return
    value = result.model_dump_json()
    # First complete response wins. Identical broker duplicates have no side effects.
    await client.set(f"{key}:result", value, ex=10, nx=True)
