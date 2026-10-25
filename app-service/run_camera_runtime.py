"""Standalone camera issuer. HTTP/MQTT ingress only submits durable jobs."""

from __future__ import annotations

import asyncio
import logging
import signal

from core.camera.runtime import CameraRuntime, camera_runtime_loop
from core.config import settings
from core.fs_broker import fs_router
from core.models import db_helper
from core.redis_helper import redis_helper

# Register publishers, never the API's shared MQTT/desktop subscribers.
from core.topologys import declare as _publishers  # noqa: F401

log = logging.getLogger(__name__)


async def run_worker() -> None:
    if not settings.camera.monotonic_runtime_enabled:
        raise RuntimeError("camera_runtime_disabled")
    if getattr(fs_router.broker, "_subscribers", {}):
        raise RuntimeError("camera_worker_must_not_consume_shared_queues")
    try:
        await redis_helper.init_pool()
        if not await redis_helper.ping():
            raise RuntimeError("camera_worker_redis_unavailable")
        # Startup failure exits visibly; the process supervisor retries. Once
        # connected, aio-pika's existing robust connection handles reconnects.
        await asyncio.wait_for(fs_router.broker.start(), timeout=15)
        log.info("Dedicated camera issuer started")
        await camera_runtime_loop(CameraRuntime(owns_issuer=True))
    finally:
        # Cancellation leaves the durable owner deadline intact. A successor
        # must perform the existing fenced epoch takeover, never resume clocks.
        await fs_router.broker.stop()
        await redis_helper.close_pool()
        await db_helper.dispose()


async def main() -> None:
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, task.cancel)
    try:
        await run_worker()
    finally:
        loop.remove_signal_handler(signal.SIGTERM)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt, asyncio.CancelledError:
        pass
