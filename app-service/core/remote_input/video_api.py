from __future__ import annotations

import json
from datetime import datetime
from collections.abc import Callable, Coroutine
from typing import Any, Literal

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict

from core.camera.native_contract import ENROLLMENT02, MEDIA11, selected_headers
from core.remote_input.video_models import Capabilities, Descriptor, ErrorDetail
from core.remote_input.video_wire import load_object


class VideoControlRoute(APIRoute):
    """Apply v2 byte/duplicate-key bounds before FastAPI discards raw JSON."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handle(request: Request) -> Response:
            revision = request.headers.get("X-L4-Camera-Contract")
            modern = (
                revision == MEDIA11
                or request.headers.get("X-L4-Camera-Cadence") is not None
                or request.headers.get("X-L4-Camera-Enrollment") == ENROLLMENT02
            )
            if modern:
                try:
                    selected_headers(request.headers)
                except ValueError as exc:
                    return JSONResponse(status_code=422, content={"detail": str(exc)})
            elif revision is not None and revision != "siplite-camera/1.0.0":
                return JSONResponse(
                    status_code=422, content={"detail": "unsupported_camera_contract"}
                )
            v2 = revision is not None or request.url.path.endswith("/video-stop")
            if request.method == "POST" and request.url.path.endswith(
                ("/stream/start", "/video-stop")
            ):
                body = await request.body()
                try:
                    parsed = json.loads(body)
                    v2 = v2 or (isinstance(parsed, dict) and parsed.get("v") == 2)
                    if v2:
                        load_object(body)
                except ValueError, TypeError:
                    if v2:
                        return JSONResponse(
                            status_code=400,
                            content={"detail": {"code": "invalid_payload"}},
                        )
            try:
                return await original(request)
            except RequestValidationError:
                if v2:
                    return JSONResponse(
                        status_code=400, content={"detail": {"code": "invalid_payload"}}
                    )
                raise

        return handle


class VideoCapabilityView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    negotiated_v2: bool
    video_capabilities: Capabilities | None


class VideoLeaseView(BaseModel):
    """Publisher-only context; the legacy shared status never exposes sessions."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)
    sn: str
    lease_id: str
    active: bool
    scope: Literal["stream", "input"]
    owner_user_id: str
    owner_session_id: str
    expires_at: datetime


class VideoStateView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[2] = 2
    sn: str
    lease_id: str
    agent_instance_id: str
    operation_id: str
    command_id: str
    confirmation: Literal["agent_ready"] | None = None
    stream_instance_id: str
    result: str
    state: str
    resolved_codec: Literal["h264", "h265"]
    descriptor: Descriptor
    actual_descriptor: Descriptor | None = None
    error: ErrorDetail | None = None
    reason: str | None = None

    @classmethod
    def from_record(cls, record: dict) -> VideoStateView:
        start = record["start"]
        return cls(
            sn=start["sn"],
            lease_id=start["lease_id"],
            agent_instance_id=start["agent_instance_id"],
            operation_id=start["operation_id"],
            command_id=start["command_id"],
            confirmation=(
                "agent_ready"
                if record["state"] == "running"
                and record.get("actual_descriptor") is not None
                else None
            ),
            stream_instance_id=start["stream_instance_id"],
            result=record["result"],
            state=record["state"],
            resolved_codec=start["resolved_codec"],
            descriptor=Descriptor.model_validate(start["descriptor"]),
            actual_descriptor=record.get("actual_descriptor"),
            error=record.get("error"),
            reason=record.get("reason"),
        )
