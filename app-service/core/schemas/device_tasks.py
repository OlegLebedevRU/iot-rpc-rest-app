from datetime import UTC, datetime
from uuid import UUID
from typing import Any, Optional, List, Dict, Literal

from pydantic import (
    BaseModel,
    Field,
    ConfigDict,
    field_validator,
    PrivateAttr,
    model_validator,
)
from core.diagnostics.schemas import validate_diagnostic_payload
from core.schemas.certificate_renewal import CertificateRenewalPayload
from core.schemas.ip_camera import validate_ip_camera_payload


# Pydantic model for tasks
class ParameterlessRpcPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dt: list[Any] = Field(max_length=0)


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
    # REST admission metadata, never part of the existing MQTT envelope.
    camera_contract_revision: Literal["siplite-camera/1.0.0"] | None = Field(
        default=None, exclude=True
    )

    payload: Optional[Dict[str, Any]] = Field(
        default=None,
        title="Task payload",
        description="Данные задачи в формате JSON, опционально",
    )

    model_config = ConfigDict(
        from_attributes=True,
        hide_input_in_errors=True,
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

    @model_validator(mode="after")
    def validate_registered_diagnostics(self):
        if self.method_code in (49, 50) and isinstance(self.payload, dict):
            for record in self.payload.get("dt", []):
                if isinstance(record, dict) and record.get("ns") == "cfg_cam":
                    key = str(record.get("k", "")).lower()
                    if not key or key in (
                        "*",
                        "user",
                        "username",
                        "password",
                        "credentials",
                        "credential_profile",
                        "cred_profile",
                    ):
                        raise ValueError(
                            "camera credentials require the private RPC166 path"
                        )
        # Other deployed methods (including legacy7010) retain their contracts.
        if self.method_code in (7000, 7001, 7002):
            self.payload = validate_diagnostic_payload(self.method_code, self.payload)
        elif self.method_code in (7003, 7004, 7005):
            self.payload = ParameterlessRpcPayload.model_validate(
                self.payload
            ).model_dump(mode="json")
        elif self.method_code == 7011:
            payload = CertificateRenewalPayload.model_validate(self.payload)
            remaining = payload.dt[0].pin_expires_at - datetime.now(UTC).timestamp()
            if self.ttl == 0 or self.ttl * 60 > remaining:
                raise ValueError(
                    "RPC TTL must be positive and no longer than remaining PIN lifetime"
                )
            self.payload = payload.model_dump(mode="json")
        elif self.method_code in (168, 169):
            from core.camera.ircut_contract import validate_ircut

            if self.camera_contract_revision is not None:
                raise ValueError("IR-cut uses its own ircut_revision")
            self.payload = validate_ircut(self.method_code, self.payload)
            if self.ttl < 1:
                raise ValueError("IR-cut operations require a positive TTL")
        elif self.method_code in range(160, 168):
            if self.camera_contract_revision is not None:
                from core.camera.contract import validate_rpc

                self.payload = validate_rpc(self.method_code, self.payload)
                if self.ttl < 1:
                    raise ValueError("camera operations require a positive TTL")
            else:
                self.payload = validate_ip_camera_payload(
                    self.method_code, self.payload
                )
        return self


class TaskRequest(BaseModel):
    id: UUID


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
    result: dict | None = None  # Теперь это словарь, а не строка

    model_config = ConfigDict(from_attributes=True)

    @field_validator("result", mode="before")
    @classmethod
    def normalize_result(cls, value: Any) -> dict | None:
        from core.rpc_redaction import redact_rpc

        if value is None or isinstance(value, dict):
            return redact_rpc(value)
        return {"value": redact_rpc(value)}


class TaskResponseResult(TaskResponseStatus):
    results: List[ResultArray]
    payload: dict[str, Any] | None = None

    @field_validator("payload", mode="before")
    @classmethod
    def redact_history_payload(cls, value: Any) -> Any:
        from core.rpc_redaction import redact_rpc

        return redact_rpc(value)

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
                            "result": {
                                "status": "OK"
                            },  # ← Изменено: теперь dict, а не строка
                        }
                    ],
                }
            ]
        }
    )


class TaskResponsePayload(TaskResponseStatus):
    _expires_at: datetime | None = PrivateAttr(default=None)
    payload: Optional[Dict[str, Any]] = Field(
        default=None,
        title="Task payload",
        description="Данные задачи в формате JSON, опционально",
    )


# Pydantic model for devices


class TaskNotify(TaskResponse):
    model_config = ConfigDict(from_attributes=True)
    header: TaskHeader
    payload_required: bool = True


class TaskListOut(TaskHeader):
    id: UUID
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
