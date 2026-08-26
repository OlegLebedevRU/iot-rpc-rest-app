from __future__ import annotations

from datetime import datetime
from ipaddress import IPv4Address
from typing import Optional, List, Any

from pydantic import BaseModel, JsonValue, computed_field
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


class Gauge(BaseModel):
    pass


class DeviceGaugesView(BaseModel):
    device_id: int
    type: str
    updated_at: datetime
    gauges: Json


class DeviceConnectView(BaseModel):
    device_id: int
    client_id: str
    connected_at: datetime | None = None
    checked_at: datetime | None = None
    last_checked_result: bool
    app_connect: bool | None = None
    svc_connect: bool | None = None
    details: DeviceConnectionDetails | dict[str, Any] | None = None

    @computed_field
    @property
    def is_app_available(self) -> Optional[bool]:
        if self.app_connect is None:
            return None
        return bool(self.last_checked_result and self.app_connect)

    @computed_field
    @property
    def is_svc_available(self) -> Optional[bool]:
        if self.svc_connect is None:
            return None
        return bool(self.last_checked_result and self.svc_connect)


class DeviceListResult(BaseModel):
    id: int
    device_id: int
    sn: str
    device_gauges: List[DeviceGaugesView | None]
    connection: Optional[DeviceConnectView]
    device_tags: List[DeviceTagPut | None]
