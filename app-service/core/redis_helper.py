from __future__ import annotations

import asyncio

from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    TimeoutError as RedisTimeoutError,
)

from core.config import settings
from core.logging_config import setup_module_logger

log = setup_module_logger(__name__, "redis.log")


class RedisHelper:
    def __init__(self) -> None:
        self._pool: ConnectionPool | None = None
        self._client: Redis | None = None
        self._custom_client: Redis | None = None
        self._lock = asyncio.Lock()

    def set_client(self, client: Redis | None) -> None:
        """Set custom or mock/fake Redis client (e.g. for testing)."""
        self._custom_client = client

    async def init_pool(self, url: str | None = None) -> None:
        """Initialize Redis connection pool."""
        async with self._lock:
            if self._custom_client is not None:
                return
            if self._client is not None:
                return
            redis_url = url or str(settings.redis.url)
            log.info("Initializing Redis connection pool for %s", redis_url)
            self._pool = ConnectionPool.from_url(
                redis_url,
                max_connections=settings.redis.pool_size,
                decode_responses=True,
                socket_timeout=settings.redis.timeout_sec,
                socket_connect_timeout=settings.redis.timeout_sec,
                health_check_interval=settings.redis.health_check_interval,
            )
            self._client = Redis(connection_pool=self._pool)

    async def close_pool(self) -> None:
        """Close Redis connection pool and release resources."""
        async with self._lock:
            if self._client is not None:
                try:
                    await self._client.aclose()
                except Exception as exc:
                    log.warning("Error closing Redis client: %s", exc)
                self._client = None
            if self._pool is not None:
                try:
                    await self._pool.disconnect()
                except Exception as exc:
                    log.warning("Error disconnecting Redis pool: %s", exc)
                self._pool = None

    def get_client(self) -> Redis:
        """Get the active Redis client."""
        if self._custom_client is not None:
            return self._custom_client
        if self._client is not None:
            return self._client
        # Lazy initialization fallback
        redis_url = str(settings.redis.url)
        self._pool = ConnectionPool.from_url(
            redis_url,
            max_connections=settings.redis.pool_size,
            decode_responses=True,
            socket_timeout=settings.redis.timeout_sec,
            socket_connect_timeout=settings.redis.timeout_sec,
            health_check_interval=settings.redis.health_check_interval,
        )
        self._client = Redis(connection_pool=self._pool)
        return self._client

    async def ping(self) -> bool:
        """Health check for Redis."""
        try:
            client = self.get_client()
            res = await client.ping()
            return bool(res)
        except (RedisConnectionError, RedisTimeoutError) as exc:
            log.warning("Redis ping failed (connection/timeout): %s", exc)
            return False
        except Exception as exc:
            log.error("Redis ping unexpected error: %s", exc)
            return False


redis_helper = RedisHelper()
