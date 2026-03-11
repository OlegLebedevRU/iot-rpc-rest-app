import uuid
from datetime import datetime
from typing import Any, Annotated, Optional, List, Dict

from pydantic import (
    BaseModel,
    Field,
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
    payload: Optional[Dict[str, Any]] = Field(
        default=None,
        title="Task payload",
        description="Данные задачи в формате JSON, опционально",
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "ext_task_id": "ext-12345",
                    "device_id": 1,
                    "method_code": 20,
                    "priority": 0,
                    "ttl": 1,
                    "payload": {"dt": [{"mt": 0}]},
                }
            ]
        },
    )


class TaskRequest(BaseModel):
    id: UUID4 | Annotated[str, AfterValidator(lambda x: uuid.UUID(x, version=4))]


# Pydantic model for response data


class TaskResponse(TaskRequest):
    created_at: int
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"id": "a1b2c3d4-e5f6-7890-g1h2-i3j4k5l6m7n8", "created_at": 1712345678}
            ]
        }
    )


class TaskResponseDeleted(TaskRequest):
    deleted_at: Optional[int] = None


class TaskResponseStatus(TaskResponse):
    header: TaskHeader
    status: int
    pending_at: Optional[int] = None
    locked_at: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)


class ResultArray(BaseModel):
    id: int
    ext_id: int
    status_code: int
    result: str = None


class TaskResponseResult(TaskResponseStatus):
    results: List[ResultArray]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "5c75b4ed-2488-4769-b23a-2afae64ea22d",
                    "created_at": 1773089559,
                    "header": {
                        "ext_task_id": "wwhdtkuwgzihwlvi2ule",
                        "device_id": 4619,
                        "method_code": 20,
                        "priority": 0,
                        "ttl": 1,
                    },
                    "status": 3,
                    "pending_at": 1773089560,
                    "locked_at": 1773089560,
                    "results": [
                        {
                            "id": 292,
                            "ext_id": 0,
                            "status_code": 200,
                            "result": '{"status":"OK"}',
                        }
                    ],
                }
            ]
        }
    )


class TaskResponsePayload(TaskResponseStatus):
    payload: Optional[Dict[str, Any]] = Field(
        default=None,
        title="Task payload",
        description="Данные задачи в формате JSON, опционально",
    )


# Pydantic model for devices


class TaskNotify(TaskResponse):
    model_config = ConfigDict(from_attributes=True)
    header: TaskHeader


class TaskListOut(TaskHeader):
    id: UUID4
    status: int
    created_at: datetime
    pending_at: Optional[datetime] = None
    locked_at: Optional[datetime] = None
    org_id: int | None  # ← Это важно!


class TaskPublish(BaseModel):
    routing_key: str
    message: Optional[str] = None
    correlation_id: Optional[str] = None
    exchange: str
    headers: Optional[dict] = None
