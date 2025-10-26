from typing import Optional, List

from pydantic import BaseModel


class DeviceConnectStatus(BaseModel):
    device_id: int
    client_id: str
    connected_at: Optional[int] = None
    checked_at: Optional[int] = None
    last_checked_result: bool
    details: Optional[str]


class DeviceTagPut(BaseModel):
    tag: str
    value: str


class DeviceGaugesView(BaseModel):
    device_id: int
    type: str
    updated_at: int
    gauges: dict


class DeviceListResult(BaseModel):
    id: int
    device_id: int
    sn: str
    device_gauges: List[DeviceGaugesView | None]
    connection: DeviceConnectStatus | None
    device_tags: List[DeviceTagPut | None]
