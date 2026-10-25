"""Linux-only isolated Gunicorn recycle exercise for the PostgreSQL actor test."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx


async def assert_web_recycles_while_issuer_survives(runtime, store, sn):
    before = await store.get(sn)
    owner = runtime.owner
    clocks = dict(runtime.clocks)
    stop = asyncio.Event()

    async def pump():
        while not stop.is_set():
            await runtime.pump(sn)
            await asyncio.sleep(0.05)

    with tempfile.TemporaryDirectory(prefix="camera-web-recycle-") as directory:
        Path(directory, "isolated_app.py").write_text(
            "import os, json\n"
            "async def app(scope, receive, send):\n"
            '    if scope["type"] != "http": return\n'
            '    body = json.dumps({"pid": os.getpid()}).encode()\n'
            '    await send({"type":"http.response.start","status":200, "headers":[]})\n'
            '    await send({"type":"http.response.body","body":body})\n',
            encoding="utf-8",
        )
        with (
            socket.socket() as listener,
            open(Path(directory, "worker.log"), "w+") as log,
        ):
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            port = listener.getsockname()[1]
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "gunicorn",
                    "isolated_app:app",
                    "--bind",
                    f"fd://{listener.fileno()}",
                    "--workers",
                    "1",
                    "--worker-class",
                    "uvicorn.workers.UvicornWorker",
                    "--max-requests",
                    "1000",
                    "--max-requests-jitter",
                    "100",
                    "--log-level",
                    "warning",
                ],
                cwd=directory,
                pass_fds=(listener.fileno(),),
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
            task = asyncio.create_task(pump())
            try:
                pids = set()
                successful = 0
                async with httpx.AsyncClient(timeout=3) as client:
                    for _ in range(1300):
                        try:
                            response = await client.get(f"http://127.0.0.1:{port}/")
                            response.raise_for_status()
                            pids.add(response.json()["pid"])
                            successful += 1
                            if len(pids) >= 2:
                                break
                        except httpx.TransportError:
                            await asyncio.sleep(0.05)
                assert len(pids) >= 2, "Actual HTTP worker did not recycle"
                assert successful >= 1000
                after = await store.get(sn)
                assert runtime.owner == owner and runtime.clocks == clocks
                for key in ("epoch", "generation", "active", "counter", "enrolled"):
                    assert after[key] == before[key], key
                assert after["last_tick"] > before["last_tick"]
                print(
                    json.dumps(
                        {
                            "isolated_http_requests": successful,
                            "distinct_http_worker_pids": len(pids),
                            "issuer_unchanged": True,
                            "active_deadline_unchanged": True,
                        }
                    )
                )
            finally:
                stop.set()
                await task
                # Only our own process group, never an existing Gunicorn/service.
                import signal

                os.killpg(proc.pid, signal.SIGTERM)
                await asyncio.to_thread(proc.wait, 15)
