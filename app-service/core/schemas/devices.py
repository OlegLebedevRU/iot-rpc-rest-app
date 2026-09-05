from __future__ import annotations

import json
from datetime import datetime
from ipaddress import IPv4Address
from typing import Optional, List, Any

from pydantic import BaseModel, JsonValue, computed_field, ConfigDict, field_validator
from pydantic_core.core_schema import JsonSchema

from core.schemas.rmq_admin import DeviceConnectionDetails

type Json = dict[str, Json] | list[Json] | str | int | float | bool | IPv4Address | None


class DeviceConnectStatus(BaseModel):
    device_id: int
    client_id: str
    connected_at: int | None = None
    checked_at: int | None = None
    last_checked_result: bool
    app_connect: bool | None = None
    svc_connect: bool | None = None
    details: DeviceConnectionDetails | dict[str, Any] | None = None


class DeviceTagPut(BaseModel):
    tag: str
    value: str


class DeviceTagView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    tag: str
    value: Optional[str] = None


class Gauge(BaseModel):
    pass


class DeviceGaugesView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    device_id: int
    type: str
    updated_at: datetime
    gauges: Json


class DeviceAuditEventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    org_id: int
    event_type: str
    actor: Optional[str] = None
    details: Optional[dict[str, Any]] = None
    created_at: datetime


class DeviceConnectView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    device_id: int
    client_id: Optional[str] = None
    connected_at: datetime | None = None
    checked_at: datetime | None = None
    last_checked_result: bool = False
    app_connect: bool | None = None
    svc_connect: bool | None = None
    details: DeviceConnectionDetails | dict[str, Any] | None = None
    is_blocked: bool = False
    violation_type: Optional[str] = None
    violation_details: Optional[dict[str, Any]] = None
    recent_audit_events: Optional[List[DeviceAuditEventView]] = None

    @field_validator("details", mode="before")
    @classmethod
    def parse_details(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return v
        return v

    @field_validator("violation_details", mode="before")
    @classmethod
    def parse_violation_details(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return v
        return v

    @computed_field
    @property
    def is_app_available(self) -> Optional[bool]:
        if self.app_connect is None:
            return None
        return bool(self.last_checked_result and self.app_connect and not self.is_blocked)

    @computed_field
    @property
    def is_svc_available(self) -> Optional[bool]:
        if self.svc_connect is None:
            return None
        return bool(self.last_checked_result and self.svc_connect and not self.is_blocked)


class DeviceListResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    sn: str
    device_gauges: List[DeviceGaugesView | None] = []
    connection: Optional[DeviceConnectView] = None
    device_tags: List[DeviceTagView | None] = []


class DeviceStats(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total: int = 0
    online: int = 0
    offline: int = 0
    blocked: int = 0


class DeviceListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: List[DeviceListResult]
    total: int
    page: int
    size: int
    pages: int
    stats: DeviceStats
