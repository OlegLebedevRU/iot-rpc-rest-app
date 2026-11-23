"""Loss-tolerant worker hints. The database remains authoritative after reconnect."""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from faststream.rabbit import RabbitQueue

from core.fs_broker import fs_router

log = logging.getLogger(__name__)
CAMERA = "app1.internal.camera.wake"
INVENTORY = "app1.internal.inventory.wake"


async def notify(queue: str, key: str = "") -> None:
    try:
        async with asyncio.timeout(0.4):
            await fs_router.broker.publish(
                key.encode(), routing_key=queue, mandatory=False
            )
    except Exception:
        log.debug(
            "Wake unavailable for %s; reconciliation will recover", queue, exc_info=True
        )


@asynccontextmanager
async def listen(name: str):
    event = asyncio.Event()
    keys: set[str] = set()

    async def receive(message):
        if len(message.body) <= 128 and len(keys) < 256:
            keys.add(message.body.decode("utf-8", errors="replace"))
        event.set()

    async def consume():
        while True:
            try:
                queue = await fs_router.broker.declare_queue(
                    RabbitQueue(
                        name,
                        durable=False,
                        arguments={"x-max-length": 256, "x-message-ttl": 10000},
                    )
                )
                tag = await queue.consume(receive, no_ack=True)
                try:
                    await asyncio.Future()
                finally:
                    with suppress(Exception):
                        await queue.cancel(tag)
            except Exception:
                log.warning("Wake listener unavailable for %s", name, exc_info=True)
                await asyncio.sleep(5)

    async def wait(delay: float):
        if not event.is_set() and delay > 0:
            with suppress(TimeoutError):
                await asyncio.wait_for(event.wait(), delay)
        event.clear()
        batch = keys.copy()
        keys.clear()
        return batch

    task = asyncio.create_task(consume())
    try:
        yield wait
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
