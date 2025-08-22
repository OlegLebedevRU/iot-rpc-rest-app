import json
from typing import Any

from pydantic import BaseModel, Field, JsonValue, field_validator, UUID4


# Pydantic model for request data
class TaskCreate(BaseModel):
    device_id: int
    method_code: int = Field(
        0,
        title='Task method code ref',
        description='this is the value of method code',
        ge=0,
        lt=65535,
    )
    priority: int = Field(
        0,
        title='Task priority',
        description='this is the value of task priority',
        ge=0,
        lt=10,
    )
    ttl: int = Field(
        1,
        title='Task ttl',
        description='this is the value (minutes) of time to live',
        ge=1,
        lt=44640,
    )
    payload: JsonValue = Field(
        "{}",
    )

    @field_validator('payload', mode='before')
    @classmethod
    def ensure_json(cls, value: Any) -> Any:
        try:
            json.loads(value)
        except (ValueError, TypeError):
            raise ValueError("'payload' is not json")
        return value


# Pydantic model for response data
class TaskRequest(BaseModel):
    id: UUID4


class TaskResponse(BaseModel):
    id: UUID4


class TaskResponseStatus(BaseModel):
    id: UUID4
    method_code: int
    device_id: int
    priority: int
    status: int
    ttl: int


class TaskResponseResult(TaskResponseStatus):
    result: str
    @field_validator('result', mode='before')
    @classmethod
    def is_exist(cls, value: str | None) -> str:
        if value is None:
            value = "{}"
        return value
