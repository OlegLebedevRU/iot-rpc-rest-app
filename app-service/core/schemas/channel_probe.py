"""Volatile transport-only wire; no RPC payload or event envelope is accepted."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class ChannelProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    v: Literal[1]
    type: Literal["channel_probe"]

    @field_validator("v", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("integer protocol version required")
        return value


class ChannelProbeEvent(ChannelProbeRequest):
    request_nonce: str

    @field_validator("request_nonce")
    @classmethod
    def canonical_nonce(cls, value: str) -> str:
        parsed = UUID(value)
        if not parsed.int or str(parsed) != value.lower():
            raise ValueError("nonzero canonical UUID required")
        return value
