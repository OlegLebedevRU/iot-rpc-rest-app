"""
Примеры данных для документации вебхуков.
"""

EXAMPLE_WEBHOOK_CREATE_UPDATE = {
    "url": "https://your-api.com/webhook/events",
    "headers": {"Authorization": "Bearer abc123"},
    "is_active": True,
}

EXAMPLE_WEBHOOK_RESPONSE = {
    "org_id": 100,
    "event_type": "msg-event",
    "url": "https://your-api.com/webhook/events",
    "headers": {"Authorization": "Bearer abc123"},
    "is_active": True,
    "created_at": "2025-04-05T10:00:00+00:00",
    "updated_at": "2025-04-05T10:05:00+00:00",
}
