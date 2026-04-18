"""
Optional FastAPI webhook receiver for LEO4 msg-task-result and msg-event.

Start with: uvicorn leo4_mcp.webhook_inbox:app --port 8766

Stores incoming webhooks in an in-memory queue accessible via /inbox endpoints.
"""
from __future__ import annotations
import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Any

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    app = FastAPI(title="LEO4 Webhook Inbox", version="0.1.0")

    _task_results: deque[dict] = deque(maxlen=1000)
    _events: deque[dict] = deque(maxlen=1000)

    @app.post("/hooks/task-result")
    async def receive_task_result(request: Request) -> JSONResponse:
        """Receive msg-task-result webhook from LEO4."""
        body = await request.json()
        _task_results.appendleft(
            {"received_at": datetime.now(timezone.utc).isoformat(), "payload": body}
        )
        return JSONResponse({"ok": True})

    @app.post("/hooks/device-event")
    async def receive_device_event(request: Request) -> JSONResponse:
        """Receive msg-event webhook from LEO4."""
        body = await request.json()
        _events.appendleft(
            {"received_at": datetime.now(timezone.utc).isoformat(), "payload": body}
        )
        return JSONResponse({"ok": True})

    @app.get("/inbox/task-results")
    async def list_task_results(limit: int = 50) -> list[dict]:
        """Return recent task result webhooks."""
        return list(_task_results)[:limit]

    @app.get("/inbox/events")
    async def list_events(limit: int = 50) -> list[dict]:
        """Return recent device event webhooks."""
        return list(_events)[:limit]

except ImportError:
    # FastAPI not installed – webhook_inbox is optional
    app = None  # type: ignore
