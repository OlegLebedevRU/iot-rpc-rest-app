from pydantic import BaseModel, HttpUrl, Field, model_validator
from typing import Dict, Optional
from datetime import datetime


class WebhookCreateUpdate(BaseModel):
    url: HttpUrl = Field(
        ..., description="URL вебхука, должен начинаться с http:// или https://"
    )
    headers: Optional[Dict[str, str]] = Field(
        None,
        description="Дополнительные заголовки (например, авторизация)",
        # example={"Authorization": "Bearer xxx", "X-Secret": "secret123"}
    )
    is_active: bool = Field(True, description="Включён ли вебхук")

    class Config:
        json_schema_extra = {
            "example": {
                "url": "https://your-api.com/webhook/events",
                "headers": {"Authorization": "Bearer abc123"},
                "is_active": True,
            }
        }


class WebhookResponse(BaseModel):
    org_id: int
    event_type: str
    url: str
    headers: Optional[Dict[str, str]]
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "org_id": 100,
                "event_type": "msg-event",
                "url": "https://your-api.com/webhook/events",
                "headers": {"Authorization": "Bearer abc123"},
                "is_active": True,
                "created_at": "2025-04-05T10:00:00+00:00",
                "updated_at": "2025-04-05T10:05:00+00:00",
            }
        }
