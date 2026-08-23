from datetime import datetime
from pydantic import BaseModel, Field


class TerminalProvisionRequest(BaseModel):
    device_id: int
    sn: str
    org_id: int
    name: str | None = None
    tags: dict[str, str] | None = None


class BatchTerminalProvisionRequest(BaseModel):
    terminals: list[TerminalProvisionRequest]


class TerminalProvisionResult(BaseModel):
    device_id: int
    sn: str
    org_id: int
    success: bool
    rmq_user_status: str | None = None
    is_online: bool = False
    connected_at: datetime | None = None
    error: str | None = None


class BatchTerminalProvisionResponse(BaseModel):
    results: list[TerminalProvisionResult]


class TerminalStatusQuery(BaseModel):
    device_ids: list[int] = Field(..., min_length=1)


class TerminalStatusResult(BaseModel):
    device_id: int
    sn: str | None = None
    org_id: int | None = None
    is_provisioned: bool
    is_online: bool
    connected_at: datetime | None = None
    checked_at: datetime | None = None


class BatchTerminalStatusResponse(BaseModel):
    statuses: list[TerminalStatusResult]
