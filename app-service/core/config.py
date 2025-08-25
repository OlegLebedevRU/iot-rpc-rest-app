import logging
from typing import Literal

from faststream.rabbit import RabbitQueue
from pydantic import AmqpDsn
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


class ApiV1Prefix(BaseModel):
    prefix: str = "/v1"
    device_tasks: str = "/device-tasks"


class ApiPrefix(BaseModel):
    prefix: str = "/api"
    v1: ApiV1Prefix = ApiV1Prefix()

class FastStreamConfig(BaseModel):
    url: AmqpDsn
    #log_format: str = WORKER_LOG_DEFAULT_FORMAT

class DatabaseConfig(BaseModel):
    url: PostgresDsn
    echo: bool = False
    echo_pool: bool = False
    pool_size: int = 50
    max_overflow: int = 10
    limit_tasks_result:int=100
    naming_convention: dict[str, str] = {
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
class RoutingKey():
    def __init__(self, prefix, sn, suffix):
        self.prefix = prefix
        self.sn = sn
        self.suffix = suffix

    def __str__(self):
        return f"{self.prefix}.{self.sn}.{self.suffix}"

    def __repr__(self):
        return f"{self.prefix}.{self.sn}.{self.suffix}"


class RabbitQXConfig(BaseModel):
    x_name:str ="amq.topic"

    prefix_dev:str = "dev"
    prefix_srv: str = "srv"
    # core -> dev
    suffix_task:str = "tsk"
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

class JobTtlConfig(BaseModel):
    tick_interval:int = 1
    id_name: str = "ttl_update_job"


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
    rmq:RabbitQXConfig= RabbitQXConfig()
    ttl_job:JobTtlConfig = JobTtlConfig()

settn = Settings()
print(str(settn))
def settn_get():
    return settn
settings = settn_get()