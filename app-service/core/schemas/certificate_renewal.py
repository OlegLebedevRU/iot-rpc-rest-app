"""RPC7011 consumes PB's purpose-bound PIN and UTC expiration contract."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CertificateRenewalItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pin: str = Field(pattern=r"^[0-9]{6}$", repr=False)
    pin_expires_at: int = Field(gt=0, le=32503680000)
    ttl_sec: Literal[120] = 120


class CertificateRenewalPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dt: list[CertificateRenewalItem] = Field(min_length=1, max_length=1)
