from datetime import datetime

from pydantic import BaseModel, Field


class DevEventBody(BaseModel):
    device_id: int
    event_type_code: int
    dev_event_id: int
    dev_timestamp: int
    payload: str


class DevEvents(DevEventBody):
    id: int


class DevEventOut(BaseModel):
    id: int
    device_id: int
    event_type_code: int
    dev_event_id: int
    created_at: datetime
    dev_timestamp: datetime
    payload: str


class DevEventFields(BaseModel):
    created_at: datetime
    value: str
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
        1,
        title="Limit rows in response",
        description="",
        ge=1,
        lt=10,
    )
