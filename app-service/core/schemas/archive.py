from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ArchiveRunRequest(BaseModel):
    source_month: str = Field(
        ...,
        description="Target closed month in YYYY-MM format",
        pattern=r"^\d{4}-\d{2}$",
    )
    consumers_passed_cursor: int | None = Field(
        None, description="Acknowledged consumer cursor (MenuBuilder)"
    )
    dry_run: bool = Field(
        False, description="Simulate without final atomic promotion or purge"
    )
    purge: bool = Field(True, description="Perform bounded purge after verification")
    volume_root: str | None = Field(None, description="Custom archive mount root")


class ArchiveBatchSummary(BaseModel):
    id: str
    source_project: str
    source_month: str
    manifest_version: str
    schema_version: str
    state: str
    total_records: int
    data_size_bytes: int
    sha256_checksum: str
    min_occurred_at: datetime
    max_occurred_at: datetime
    through_cursor: int | None
    consumers_passed_cursor: int
    created_at: datetime
    verified_at: datetime | None
    purged_at: datetime | None
    error_details: dict[str, Any] | None


class ArchiveBatchDetail(ArchiveBatchSummary):
    manifest_payload: dict[str, Any]
