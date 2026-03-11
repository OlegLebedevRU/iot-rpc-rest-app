from pydantic import BaseModel, HttpUrl, Field
from typing import Dict, Optional
from datetime import datetime
from core.examples import EXAMPLE_WEBHOOK_RESPONSE, EXAMPLE_WEBHOOK_CREATE_UPDATE


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
        json_schema_extra = {"example": EXAMPLE_WEBHOOK_CREATE_UPDATE}


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
        json_schema_extra = {"example": EXAMPLE_WEBHOOK_RESPONSE}
