from datetime import datetime
from ipaddress import IPv4Address
from typing import Optional, List

from pydantic import BaseModel, JsonValue
from pydantic_core.core_schema import JsonSchema

from core.schemas.rmq_admin import DeviceConnectionDetails

type Json = dict[str, Json] | list[Json] | str | int | float | bool | IPv4Address | None


class DeviceConnectStatus(BaseModel):
    device_id: int
    client_id: str
    connected_at: Optional[int] = None
    checked_at: Optional[int] = None
    last_checked_result: bool
    details: DeviceConnectionDetails  # Optional[Json]


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
    connected_at: Optional[datetime] = None
    checked_at: Optional[datetime] = None
    last_checked_result: bool
    details: Optional[DeviceConnectionDetails]  # Optional[Json]


class DeviceListResult(BaseModel):
    id: int
    device_id: int
    sn: str
    device_gauges: List[DeviceGaugesView | None]
    connection: Optional[DeviceConnectView]
    device_tags: List[DeviceTagPut | None]
