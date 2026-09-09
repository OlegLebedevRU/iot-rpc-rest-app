from __future__ import annotations

import asyncio
import time
from uuid import UUID


class TokenBucket:
    def __init__(self, rate_per_sec: float, capacity: float | None = None) -> None:
        self.rate = float(rate_per_sec)
        self.capacity = float(capacity if capacity is not None else rate_per_sec)
        self.tokens = self.capacity
        self.last_check = time.monotonic()

    def allow(self, cost: float = 1.0) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_check
        self.last_check = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[tuple[UUID, str], TokenBucket] = {}
        self._lock = asyncio.Lock()

    async def check_rate_limit(
        self, lease_id: UUID, cmd_type: str, rate_per_sec: float
    ) -> bool:
        async with self._lock:
            key = (lease_id, cmd_type)
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = TokenBucket(rate_per_sec=rate_per_sec)
                self._buckets[key] = bucket
            return bucket.allow()

    async def cleanup_lease(self, lease_id: UUID) -> None:
        async with self._lock:
            keys_to_remove = [k for k in self._buckets if k[0] == lease_id]
            for k in keys_to_remove:
                self._buckets.pop(k, None)


rate_limiter = RateLimiter()
