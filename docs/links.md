# 🔗 Links & References

> **Файл:** `docs/links.md`
> **Назначение:** быстрый навигатор по внешним спецификациям и внутренним опорным документам Leo4

---

## 📚 Внутренние опорные документы

### RPC и task workflow

| Документ | Назначение |
|---|---|
| [`mqtt-rpc-protocol.md`](./mqtt-rpc-protocol.md) | Базовая спецификация MQTT RPC: топики, lifecycle, polling / trigger |
| [`method-codes-reference.md`](./method-codes-reference.md) | Единый источник истины по `method_code`, совместимости и форматам `payload.dt` |
| [`mqtt-rpc-client-flow.md`](./mqtt-rpc-client-flow.md) | Mermaid-диаграммы RPC-потоков |
| [`mqtt-rpc-correlation-matrix.md`](./mqtt-rpc-correlation-matrix.md) | Матрица передачи `correlationData` по этапам RPC |
| [`1-task-workflow-doc.md`](./1-task-workflow-doc.md) | REST workflow задач |
| [`TTL.md`](./TTL.md) | TTL и правила выборки задач при polling |

### Events и совместимость

| Документ | Назначение |
|---|---|
| [`event-types-reference.md`](./event-types-reference.md) | Реестр `event_type_code` |
| [`event-property-tags.md`](./event-property-tags.md) | Единый источник истины по тегам `3xx` / `4xx` |
| [`event-protocol-mqtt.md`](./event-protocol-mqtt.md) | Формат MQTT-событий |
| [`2-events-api-format-description.md`](./2-events-api-format-description.md) | REST API для событий устройств |

> ℹ️ Для сценария `l4-hmi` + `method_code = 17` (`UI-Catalog`) используйте связку:
> [`method-codes-reference.md`](./method-codes-reference.md) → [`event-types-reference.md`](./event-types-reference.md) → [`event-property-tags.md`](./event-property-tags.md).

---

## 🌍 Внешние спецификации и справочные ссылки

### Security / PKI / MQTT

- X.509 — https://datatracker.ietf.org/group/pkix/about/
- RabbitMQ MQTT X.509 auth — https://www.rabbitmq.com/docs/mqtt#tls-certificate-authentication
- RabbitMQ topic authorization — https://www.rabbitmq.com/docs/access-control#topic-authorisation
- RabbitMQ example config — https://github.com/rabbitmq/rabbitmq-server/blob/main/deps/rabbit/docs/rabbitmq.conf.example
- Creating CA hierarchy — https://cryptography.io/en/latest/x509/tutorial/#creating-a-ca-hierarchy

### Python / FastAPI / SQLAlchemy

- FastAPI lifespan events — https://fastapi.tiangolo.com/advanced/events/#lifespan-function
- SQLAlchemy create engine — https://docs.sqlalchemy.org/en/20/core/engines.html#sqlalchemy.create_engine
- SQLAlchemy constraint naming conventions — https://docs.sqlalchemy.org/en/20/core/constraints.html#constraint-naming-conventions
- Alembic cookbook — https://alembic.sqlalchemy.org/en/latest/cookbook.html
- Alembic naming conventions — https://alembic.sqlalchemy.org/en/latest/naming.html#integration-of-naming-conventions-into-operations-autogenerate
- Alembic + asyncio recipe — https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic
- Python typing — https://docs.python.org/3/library/typing.html
- Pydantic settings / dotenv — https://docs.pydantic.dev/latest/concepts/pydantic_settings/#dotenv-env-support
- Pydantic settings / env variables — https://docs.pydantic.dev/latest/concepts/pydantic_settings/#parsing-environment-variable-values
- orjson — https://github.com/ijl/orjson
- FastAPI ORJSONResponse — https://fastapi.tiangolo.com/advanced/custom-response/#use-orjsonresponse

### Misc

- case converter — https://github.com/mahenzon/ri-sdk-python-wrapper/blob/master/ri_sdk_codegen/utils/case_converter.py

---

## ✅ Как пользоваться этим файлом

- Ищете **контракт RPC** → начните с [`method-codes-reference.md`](./method-codes-reference.md)
- Ищете **транспортные детали MQTT RPC** → откройте [`mqtt-rpc-protocol.md`](./mqtt-rpc-protocol.md)
- Ищете **совместимость событий / тегов** → откройте [`event-types-reference.md`](./event-types-reference.md) и [`event-property-tags.md`](./event-property-tags.md)
- Ищете **внешнюю библиотечную или инфраструктурную спецификацию** → используйте соответствующий раздел выше
