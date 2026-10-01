from datetime import UTC, datetime
from typing import Optional, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class DevEventBody(BaseModel):
    device_id: int
    event_type_code: int
    dev_event_id: int
    dev_timestamp: int
    payload: Optional[Dict] = None


class DevEvents(DevEventBody):
    id: int


class DevEventOut(BaseModel):
    id: int
    device_id: int
    event_type_code: int
    dev_event_id: int
    created_at: datetime
    dev_timestamp: datetime
    payload: Optional[Dict] = None


class UserEventSearchRequest(BaseModel):
    device_id: int = Field(gt=0)
    correlation_id: UUID | None = None
    events_include: list[int] | None = Field(default=None, min_length=1, max_length=100)
    after_event_id: int | None = Field(default=None, gt=0)
    created_from: datetime | None = None
    created_to: datetime | None = None
    limit: int = Field(default=50, ge=1, le=100)

    @field_validator("correlation_id", mode="before")
    @classmethod
    def validate_uuid(cls, value: Any) -> Any:
        # Match l4con's canonical 8-4-4-4-12 format, accepting either case.
        if isinstance(value, str):
            parsed = UUID(value)
            if str(parsed) != value.lower():
                raise ValueError("correlation_id must use UUID 8-4-4-4-12 format")
        return value

    @field_validator("events_include")
    @classmethod
    def validate_codes(cls, codes: list[int] | None) -> list[int] | None:
        if codes is not None and any(code < 900 or code > 999 for code in codes):
            raise ValueError("events_include must contain only codes 900–999")
        return codes

    @field_validator("created_from", "created_to")
    @classmethod
    def validate_time(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("time boundaries must include a timezone")
            return value.astimezone(UTC)
        return value

    @model_validator(mode="after")
    def validate_interval(self) -> "UserEventSearchRequest":
        if (
            self.created_from is not None
            and self.created_to is not None
            and self.created_from >= self.created_to
        ):
            raise ValueError("created_from must be earlier than created_to")
        return self


class UserEventSearchResponse(BaseModel):
    items: list[DevEventOut]
    next_after_event_id: int | None
    has_more: bool


class DevEventFields(BaseModel):
    created_at: datetime
    value: str | int | float | bool | dict[str, Any] | list[Any] | None
    interval_sec: int


class DevEventFieldsRequest(BaseModel):
    device_id: int
    event_type_code: int = Field(
        44,
        title="Event type code",
        description="this is the value of event code",
        ge=0,
        lt=65535,
    )
    tag: int = Field(
        338,
        title="Event tag code",
        description="this is the value of tag code",
        ge=0,
        lt=65535,
    )
    interval_m: int = Field(
        15,
        title="Time interval in minutes from now_time",
        description="",
        ge=1,
        lt=3600,
    )
    limit: int = Field(
        50,
        title="Limit rows in response",
        description="",
        ge=1,
        le=100,
    )
