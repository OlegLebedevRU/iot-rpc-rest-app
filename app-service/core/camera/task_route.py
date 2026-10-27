"""Reject duplicate keys and never reflect task input in validation errors."""

import json

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute


def _ircut_read_only(parsed: dict) -> bool:
    if parsed.get("method_code") not in (168, 169):
        return False
    payload = parsed.get("payload")
    dt = payload.get("dt") if isinstance(payload, dict) else None
    return (
        isinstance(dt, list)
        and len(dt) == 1
        and isinstance(dt[0], dict)
        and dt[0].get("action") in ("inspect", "status")
    )


class CameraTaskRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            if request.method == "POST":

                def unique(pairs):
                    value = {}
                    for key, item in pairs:
                        if key in value:
                            raise ValueError("duplicate_key")
                        value[key] = item
                    return value

                try:
                    body = await request.body()
                    parsed = json.loads(body, object_pairs_hook=unique)
                    if (
                        isinstance(parsed, dict)
                        and (
                            parsed.get("camera_contract_revision") is not None
                            or parsed.get("method_code") in (168, 169)
                        )
                        and parsed.get("method_code") != 160
                        and not _ircut_read_only(parsed)
                        and (
                            request.headers.get("X-Role", "").lower() in ("viewer", "4")
                            or request.headers.get("X-Role-Id") == "4"
                        )
                    ):
                        return JSONResponse(
                            status_code=403,
                            content={"detail": "camera_write_forbidden"},
                        )
                    if (
                        isinstance(parsed, dict)
                        and type(parsed.get("method_code")) is int
                        and parsed["method_code"] in range(160, 170)
                    ):
                        if len(body) > 12288:
                            raise ValueError("camera_request_too_large")
                except ValueError, TypeError, RecursionError:
                    return JSONResponse(
                        status_code=422, content={"detail": "invalid_task_payload"}
                    )
            try:
                return await original(request)
            except RequestValidationError:
                return JSONResponse(
                    status_code=422, content={"detail": "invalid_task_payload"}
                )

        return handle
