from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.schemas.remote_sessions import validate_no_commercial_fields


class DeviceProvisionStatus(StrEnum):
    REQUESTED = "requested"
    PROVISIONED = "provisioned"
    FAILED = "failed"


SN_PATTERN = re.compile(r"^[0-9A-Za-z_-]{6,32}$")
OPERATION_ID_PATTERN = re.compile(r"^[0-9a-fA-F-]{36}$")


class DeviceProvisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(..., description="UUID for idempotency")
    contract_version: str = Field("1.0.0", description="Contract version")
    tenant_id: int = Field(..., ge=1, description="Tenant / Organization ID")
    terminal_id: int = Field(..., ge=1, description="Terminal identifier")
    sn: str = Field(..., description="Device serial number")
    device_id: int | None = Field(None, ge=1, description="Optional explicit internal device ID")
    correlation_id: str | None = Field(None, description="End-to-end correlation ID")
    requested_by_user_id: str | None = Field(None, description="Requesting user ID")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional device metadata")

    @field_validator("operation_id")
    @classmethod
    def validate_operation_id(cls, v: str) -> str:
        val = str(v).strip()
        if not val:
            raise ValueError("operation_id cannot be empty")
        if not OPERATION_ID_PATTERN.match(val):
            raise ValueError(f"operation_id '{val}' does not match UUID pattern")
        return val

    @field_validator("sn")
    @classmethod
    def validate_sn(cls, v: str) -> str:
        val = str(v).strip()
        if not val:
            raise ValueError("sn cannot be empty")
        if not SN_PATTERN.match(val):
            raise ValueError(f"sn '{val}' does not match pattern '^[0-9A-Za-z_-]{{6,32}}$'")
        return val

    @field_validator("correlation_id")
    @classmethod
    def validate_correlation_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        val = str(v).strip()
        return val or None

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, v: dict[str, Any]) -> dict[str, Any]:
        validate_no_commercial_fields(v)
        return v


class DeviceProvisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    operation_id: str = Field(..., description="UUID for idempotency")
    status: DeviceProvisionStatus = Field(..., description="requested, provisioned, or failed")
    tenant_id: int = Field(..., description="Tenant / Organization ID")
    terminal_id: int = Field(..., description="Terminal identifier")
    device_id: int = Field(..., description="Device internal ID")
    sn: str = Field(..., description="Device serial number")
    contract_version: str = Field("1.0.0", description="Contract version")
    correlation_id: str | None = Field(None, description="End-to-end correlation ID")
    replayed_flag: bool = Field(False, description="True if response is an idempotent replay")
    created_at: datetime = Field(..., description="Creation UTC timestamp")
    provisioned_at: datetime | None = Field(None, description="Provisioning completion UTC timestamp")
    error_code: str | None = Field(None, description="Error code if status is failed")
    error_message: str | None = Field(None, description="Error description if status is failed")


class DeviceProvisionErrorDetail(BaseModel):
    error_code: str = Field(..., description="Structured error code")
    message: str = Field(..., description="Human-readable error explanation")
    operation_id: str | None = Field(None, description="Operation ID associated with error")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Error timestamp UTC")


class DeviceProvisionErrorResponse(BaseModel):
    detail: DeviceProvisionErrorDetail
