from __future__ import annotations
from typing import Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEO4_", env_file=".env", extra="ignore")

    api_url: str = "https://dev.leo4.ru/api/v1"
    api_key: str = "ApiKey CHANGE_ME"
    dry_run: bool = False
    allowed_device_ids: list[int] = []
    timeout_s: float = 30.0
    http_retries: int = 3
    known_devices: list[dict] = []

    @field_validator("allowed_device_ids", mode="before")
    @classmethod
    def parse_allowed(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v

    @field_validator("known_devices", mode="before")
    @classmethod
    def parse_known(cls, v):
        if isinstance(v, str):
            import json
            return json.loads(v) if v.strip() else []
        return v


settings = Settings()
