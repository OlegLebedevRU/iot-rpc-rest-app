"""Middleware to count API requests for billing per org_id."""

from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from core.logging_config import setup_module_logger

log = setup_module_logger(__name__, "billing_middleware.log")


class BillingApiCounterMiddleware(BaseHTTPMiddleware):
    """Publishes a billing 'api' event for each successful API request that has an org_id."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Only count successful API requests under /api/
        if (
            response.status_code < 400
            and request.url.path.startswith("/api/")
        ):
            org_id = getattr(request.state, "billing_org_id", None)
            if org_id is not None and org_id > 0:
                try:
                    from core.services.billing_publish import publish_billing_event

                    await publish_billing_event(
                        org_id=org_id,
                        device_id=0,
                        counter_type="api",
                    )
                except Exception as e:
                    log.debug("Billing API counter error (non-critical): %s", e)

        return response
