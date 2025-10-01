from typing import Optional

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
