import logging
import uuid
from typing import Literal
from pydantic import AmqpDsn, UUID4, HttpUrl
from pydantic import BaseModel
from pydantic import PostgresDsn
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


LOG_DEFAULT_FORMAT = (
    "[%(asctime)s.%(msecs)03d] %(module)10s:%(lineno)-3d %(levelname)-7s - %(message)s"
)

WORKER_LOG_DEFAULT_FORMAT = "[%(asctime)s.%(msecs)03d][%(processName)s] %(module)16s:%(lineno)-3d %(levelname)-7s - %(message)s"


class RunConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class GunicornConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    timeout: int = 900


class LoggingConfig(BaseModel):
    log_level: Literal[
        "debug",
        "info",
        "warning",
        "error",
        "critical",
    ] = "info"
    log_format: str = LOG_DEFAULT_FORMAT
    date_format: str = "%Y-%m-%d %H:%M:%S"

    @property
    def log_level_value(self) -> int:
        return logging.getLevelNamesMapping()[self.log_level.upper()]

    @property
    def fs_log_level_value(self) -> int:
        return logging.getLevelNamesMapping()["WARNING"]


#  /var/log/app


class ApiV1Prefix(BaseModel):
    prefix: str = "/v1"
    device_tasks: str = "/device-tasks"
    admin: str = "/admin"
    device_events: str = "/device-events"
    devices: str = "/devices"
    accounts: str = "/accounts"


class ApiPrefix(BaseModel):
    prefix: str = "/api"
    v1: ApiV1Prefix = ApiV1Prefix()


class FastStreamConfig(BaseModel):
    url: AmqpDsn
    max_consumers: int = 5
    # log_format: str = WORKER_LOG_DEFAULT_FORMAT


class DatabaseConfig(BaseModel):
    url: PostgresDsn
    echo: bool = False
    echo_pool: bool = False
    pool_size: int = 50
    max_overflow: int = 10
    limit_tasks_result: int = 1000
    naming_convention: dict[str, str] = {
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }


class RoutingKey:
    def __init__(self, prefix, sn, suffix):
        self.prefix = prefix
        self.sn = sn
        self.suffix = suffix

    def __str__(self):
        return f"{self.prefix}.{self.sn}.{self.suffix}"

    def __repr__(self):
        return f"{self.prefix}.{self.sn}.{self.suffix}"


class RabbitQXConfig(BaseModel):
    x_name: str = "amq.topic"
    x_name_direct: str = "amq.direct"
    def_queue_args: dict = {"x-message-ttl": 600000}
    prefix_dev: str = "dev"
    prefix_srv: str = "srv"
    # core -> dev
    suffix_task: str = "tsk"
    suffix_event_ack: str = "eva"
    suffix_response: str = "rsp"
    suffix_result_ack: str = "rac"
    # dev -> core
    req_queue_name: str = "req"
    ack_queue_name: str = "ack"
    res_queue_name: str = "res"
    evt_queue_name: str = "evt"
    routing_key_dev_ack: str = str(RoutingKey(prefix="dev", sn="*", suffix="ack"))
    routing_key_dev_request: str = str(RoutingKey(prefix="dev", sn="*", suffix="req"))
    routing_key_dev_result: str = str(RoutingKey(prefix="dev", sn="*", suffix="res"))
    routing_key_dev_event: str = str(RoutingKey(prefix="dev", sn="*", suffix="evt"))
    api_clients_queue: str = "rmq_api_client_action"


class JobTtlConfig(BaseModel):
    tick_interval: int = 1
    id_name: str = "ttl_update_job"
    queue_name: str = "core_jobs"


class TaskProcessingConfig(BaseModel):
    zero_corr_id: UUID4 = uuid.UUID(int=0)
    nop_resp: str = '{"method_code":0}'


class Leo4CloudConfig(BaseModel):
    url: HttpUrl
    api_key: str
    admin_url: HttpUrl


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env.template", ".env"),
        case_sensitive=False,
        env_nested_delimiter="__",
        env_prefix="APP_CONFIG__",
    )

    run: RunConfig = RunConfig()
    gunicorn: GunicornConfig = GunicornConfig()
    logging: LoggingConfig = LoggingConfig()
    api: ApiPrefix = ApiPrefix()
    faststream: FastStreamConfig
    db: DatabaseConfig
    rmq: RabbitQXConfig = RabbitQXConfig()
    ttl_job: JobTtlConfig = JobTtlConfig()
    task_proc_cfg: TaskProcessingConfig = TaskProcessingConfig()
    leo4: Leo4CloudConfig


settn = Settings()
print(str(settn))


def settn_get():
    return settn


settings = settn_get()

logging.basicConfig(
    level=logging.INFO,
    format=settings.logging.log_format,
    datefmt=settings.logging.date_format,
   # filename="/var/log/app/broker.log",
    filemode="w",
)