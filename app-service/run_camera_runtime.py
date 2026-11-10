"""Standalone camera issuer. HTTP/MQTT ingress only submits durable jobs."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import threading
import time

from core.camera.runtime import CameraRuntime, camera_runtime_loop
from core.camera.runtime_store import AuthorityStore
from core.config import settings
from core.fs_broker import fs_router
from core.models import db_helper
from core.models.db_helper import DatabaseHelper
from core.redis_helper import redis_helper

# Register publishers, never the API's shared MQTT/desktop subscribers.
from core.topologys import declare as _publishers  # noqa: F401

log = logging.getLogger(__name__)


def watch_progress(runtime, stopped):
    # A coroutine timeout can itself wedge during driver cancellation/cleanup.
    # This independent watchdog exits only this dedicated issuer process.
    while not stopped.wait(5):
        if time.monotonic() - runtime.worker_progress > 60:
            log.critical("Camera issuer made no progress for60s; restarting")
            os._exit(1)


async def run_worker() -> None:
    if not settings.camera.monotonic_runtime_enabled:
        raise RuntimeError("camera_runtime_disabled")
    if getattr(fs_router.broker, "_subscribers", {}):
        raise RuntimeError("camera_worker_must_not_consume_shared_queues")
    worker_db = DatabaseHelper(
        url=str(settings.db.url),
        pool_size=1,
        max_overflow=0,
        pool_timeout=5,
        connect_args={
            "timeout": 5,
            "command_timeout": 5,
            "server_settings": {"statement_timeout": "5000", "lock_timeout": "2000"},
        },
    )
    runtime = CameraRuntime(AuthorityStore(worker_db.session_factory), owns_issuer=True)
    stopped = threading.Event()
    threading.Thread(
        target=watch_progress, args=(runtime, stopped), daemon=True
    ).start()
    try:
        await redis_helper.init_pool()
        if not await redis_helper.ping():
            raise RuntimeError("camera_worker_redis_unavailable")
        # Startup failure exits visibly; the process supervisor retries. Once
        # connected, aio-pika's existing robust connection handles reconnects.
        await asyncio.wait_for(fs_router.broker.start(), timeout=15)
        log.info("Dedicated camera issuer started")
        await camera_runtime_loop(runtime)
    finally:
        # Cancellation leaves the durable owner deadline intact. A successor
        # must perform the existing fenced epoch takeover, never resume clocks.
        try:
            await fs_router.broker.stop()
        finally:
            try:
                await redis_helper.close_pool()
            finally:
                try:
                    await worker_db.dispose()
                    await db_helper.dispose()
                finally:
                    stopped.set()


async def main() -> None:
    task = asyncio.current_task()
    assert task is not None
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, task.cancel)
    try:
        await run_worker()
    finally:
        loop.remove_signal_handler(signal.SIGTERM)


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt, asyncio.CancelledError):
        asyncio.run(main())
