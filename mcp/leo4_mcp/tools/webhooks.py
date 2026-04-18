"""MCP tools for webhook management."""
from __future__ import annotations
from typing import Optional

from ..client import get_client
from ..config import settings
from ..dry_run import dry_webhook, dry_list_webhooks

SUPPORTED_EVENT_TYPES = ("msg-event", "msg-task-result")


async def configure_webhook(
    event_type: str,
    url: str,
    headers: Optional[dict] = None,
    is_active: bool = True,
) -> dict:
    """
    Create or update a webhook via LEO4 PUT /webhooks/{event_type}.

    Supported event_type values:
      - "msg-event": device events (e.g. cell opened, sensor readings)
      - "msg-task-result": task delivery confirmations

    Using webhooks is recommended over polling for production deployments.

    Args:
        event_type: "msg-event" or "msg-task-result"
        url: HTTPS URL that will receive POST requests from LEO4
        headers: Optional additional headers to include in webhook POST (e.g. auth)
        is_active: Whether the webhook is active (default True)

    Returns:
        Webhook configuration object
    """
    if event_type not in SUPPORTED_EVENT_TYPES:
        raise ValueError(
            f"Unsupported event_type '{event_type}'. "
            f"Use one of: {SUPPORTED_EVENT_TYPES}"
        )
    if settings.dry_run:
        return dry_webhook(event_type=event_type, url=url)

    client = get_client()
    body: dict = {"url": url, "is_active": is_active}
    if headers:
        body["headers"] = headers

    return await client.put(f"/webhooks/{event_type}", json=body)


async def list_webhooks() -> list:
    """
    List all webhooks for the current organisation via LEO4 GET /webhooks/.

    Returns:
        List of webhook configuration objects
    """
    if settings.dry_run:
        return dry_list_webhooks()

    client = get_client()
    return await client.get("/webhooks/")
