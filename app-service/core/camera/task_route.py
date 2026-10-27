"""Reject duplicate keys and never reflect task input in validation errors."""

import json

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute


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
