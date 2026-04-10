"""Helper to publish billing counter events via RabbitMQ."""

import json

from core.logging_config import setup_module_logger
from core.topologys.declare import job_publisher, direct_exchange, billing_action

log = setup_module_logger(__name__, "billing_publish.log")


async def publish_billing_event(
    org_id: int,
    device_id: int,
    counter_type: str,
    value: int = 1,
    payload_bytes: int = 0,
) -> None:
    """Publish a billing counter increment event to the billing queue.

    Args:
        org_id: Organization identifier.
        device_id: Device identifier (0 for API-only events).
        counter_type: One of 'evt', 'res', 'api', 'activity'.
        value: Increment value (default 1).
        payload_bytes: Payload size in bytes (for RES messages).
    """
    try:
        message = json.dumps({
            "org_id": org_id,
            "device_id": device_id,
            "counter_type": counter_type,
            "value": value,
            "payload_bytes": payload_bytes,
        })
        await job_publisher.publish(
            routing_key=billing_action.name,
            message=message,
            exchange=direct_exchange,
            expiration=10 * 60_000,
        )
    except Exception as e:
        log.error(
            "Failed to publish billing event: org_id=%d device_id=%d type=%s error=%s",
            org_id, device_id, counter_type, e,
        )
