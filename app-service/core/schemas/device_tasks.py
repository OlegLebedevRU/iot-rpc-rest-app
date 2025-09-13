import json
import uuid
from datetime import datetime, time
from typing import Any, Annotated, Optional
from pydantic import (
    BaseModel,
    Field,
    JsonValue,
    field_validator,
    UUID4,
    ConfigDict,
    AfterValidator,
)


# Pydantic model for tasks
class TaskHeader(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    ext_task_id: str
    device_id: int
    method_code: int = Field(
        20,
        title="Task method code ref",
        description="this is the value of method code",
        ge=0,
        lt=65535,
    )
    priority: int = Field(
        0,
        title="Task priority",
        description="this is the value of task priority",
        ge=0,
        lt=10,
    )
    ttl: int = Field(
        1,
        title="Task ttl",
        description="this is the value (minutes) of time to live",
        ge=0,
        lt=44640,
    )


# Pydantic model for requests


class TaskCreate(TaskHeader):
    payload: JsonValue = Field(
        '{"dt":[{"mt":0}]}',
    )

    @field_validator("payload", mode="before")
    @classmethod
    def ensure_json(cls, value: Any) -> Any:
        try:
            json.loads(value)
        except (ValueError, TypeError):
            raise ValueError("'payload' is not json")
        return value


class TaskRequest(BaseModel):
    id: UUID4 | Annotated[str, AfterValidator(lambda x: uuid.UUID(x, version=4))]


# Pydantic model for response data


class TaskResponse(TaskRequest):
    created_at: int


class TaskResponseDeleted(TaskRequest):
    deleted_at: Optional[int] = None


class TaskResponseStatus(TaskResponse):
    header: TaskHeader
    status: int
    pending_at: Optional[int] = None
    locked_at: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)


class TaskResponseResult(TaskResponseStatus):
    result: str

    # model_config = ConfigDict(from_attributes=True)
    @field_validator("result", mode="before")
    @classmethod
    def is_exist(cls, value: str | None) -> str:
        if value is None:
            value = "{}"
        return value


class TaskResponsePayload(TaskResponseStatus):
    payload: str


# Pydantic model for devices


class TaskNotify(TaskResponse):
    model_config = ConfigDict(from_attributes=True)
    header: TaskHeader
