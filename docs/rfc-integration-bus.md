# RFC: Безопасная интеграционная шина RabbitMQ для доменных приложений

| Поле | Значение |
|------|----------|
| **RFC** | `integration-bus-001` |
| **Статус** | Proposed |
| **Версия** | 1.0 |
| **Дата** | 2026-08-11 |
| **Область** | Leo4 IoT Platform — транспорт / multi-tenant integration |
| **Касается** | RabbitMQ topology, ACL, app-service publishers/subscribers |
| **Не ломает** | MQTT device protocol, REST API v1, webhooks |

---

## 1. Abstract

Предлагается **выделенная интеграционная шина** на уже существующем RabbitMQ (vhost `/`):

- outbound: exchange `integration.topic` → per-tenant очереди `q.int.<org_id>.*`;
- inbound: exchange `integration.commands` (type **topic**) ← команды доменных сервисов;
- per-tenant RabbitMQ user `int.<org_id>` с жёсткими vhost/topic permissions;
- подключение доменных приложений по **AMQPS** (TLS 1.2+).

Шина **дополняет**, а не заменяет REST API и HTTP webhooks. Цель — guaranteed delivery, backpressure и изоляция tenant’ов для серверных доменных приложений (например, `postamat-domain-service`).

---

## 2. Motivation

### 2.1 As-is

Платформа Leo4 — транспортно-событийное ядро (FastAPI + FastStream + RabbitMQ MQTT plugin).

| Канал | Как работает сегодня |
|-------|----------------------|
| Устройства | MQTT 5 over TLS (mTLS, CN = SN), топики `dev.<SN>.*` / `srv.<SN>.*` на `amq.topic` |
| Внутренние job’ы | `amq.direct`: `core_jobs`, `rmq_api_client_action`, `webhook_action`, `billing_counter_action` |
| Внешняя доставка | Только **HTTP webhooks** (`OrgWebhook` → очередь `webhook_action` → httpx POST) |
| Доменные команды | Только **REST** `POST /device-tasks/` |

Факты из кода:

- топология: `app-service/core/topologys/declare.py` — exchanges `amq.topic`, `amq.direct`;
- device ACL: `app-service/core/integrations/rmq_admin_api.py` — topic permissions на `amq.topic` (`write: ^dev.{sn}.*`, `read: ^srv.{sn}.*`);
- события → webhook: `DeviceEventsCollect.add()` публикует в `webhook_action` только для **новых** non-gauge событий;
- gauge `event_type_code = 44` обновляет gauge и **не** создаёт event row / webhook.

### 2.2 Проблемы

1. **Webhooks** — at-most-once с ретраями HTTP; нет consumer backpressure, нет безопасного replay, нет native ack.
2. **Нет AMQP-контракта** для server-side domain services: они вынуждены либо поллить REST, либо принимать HTTP push.
3. **Риск смешения** device MQTT ACL и integration traffic, если подписывать внешние сервисы напрямую на `amq.topic`.
4. **Нужна tenant-изоляция** на уровне RabbitMQ (не только `x-api-key` в REST).

### 2.3 Goals

- Изолированный integration plane (отдельные exchanges + per-org queues).
- Per-tenant credentials с минимальными правами (least privilege).
- Стабильный envelope и routing key convention.
- Команды от domain-service → существующий `DeviceTasksService` / MQTT RPC без обхода ACL устройств.
- Сохранение webhooks и REST без breaking changes.

### 2.4 Non-goals

- Отдельный vhost / shovel / federation (v1).
- Замена MQTT device protocol или `amq.topic` device bindings.
- Kafka/NATS или иной брокер.
- Удаление webhooks.
- Гарантия «exactly-once» end-to-end (цель v1 — **at-least-once** + idempotency keys).
- Реализация кода в этом RFC (только спецификация; implementation outline — §16).

---

## 3. Terminology

| Термин | Определение |
|--------|-------------|
| **org_id** | Идентификатор организации (tenant) в платформе |
| **Integration tenant** | Доменное приложение, подключённое к шине от имени org |
| **Tenant user** | RabbitMQ user `int.<org_id>` |
| **Channel** | Логический поток: `events`, `snapshots`, `status`, `tasks`, `errors`, `commands` |
| **Envelope** | Единая JSON-обёртка интеграционного сообщения (§8) |
| **Platform publisher** | Код app-service, публикующий в `integration.topic` под platform credentials |
| **Command** | Inbound сообщение в `integration.commands`, порождающее device task |

См. также: [`docs/glossary.md`](glossary.md), [`docs/task_states.md`](task_states.md).

---

## 4. Current architecture (as-is)

```
Device ──MQTT/mTLS──► amq.topic ──► queues: req, ack, evt, res, out
                              │
Domain app ──HTTPS──► REST API / webhooks (HTTP callbacks)
                              │
Internal ──────────► amq.direct ──► core_jobs, webhook_action,
                                    rmq_api_client_action, billing_counter_action
```

### 4.1 Exchanges и очереди

| Exchange | Type | Назначение |
|----------|------|------------|
| `amq.topic` | topic | Device MQTT plane (`dev.*` / `srv.*`) |
| `amq.direct` | direct | Internal jobs / webhooks / billing |

| Queue | Binding / RK | Назначение |
|-------|--------------|------------|
| `req` | `dev.*.req` | poll задач |
| `ack` | `dev.*.ack` | ACK задачи |
| `evt` | `dev.*.evt` | события устройства |
| `res` | `dev.*.res` | результат задачи |
| `out` | `dev.*.out` | diagnostics |
| `core_jobs` | `core_jobs` @ direct | TTL jobs |
| `webhook_action` | `webhook_action` @ direct | HTTP webhook dispatch |
| `rmq_api_client_action` | `rmq_api_client_action` @ direct | online/presence |
| `billing_counter_action` | `billing_counter_action` @ direct | billing counters |

### 4.2 Device security (as-is)

- Auth: mTLS, username ≈ SN (CN сертификата).
- Vhost `/`: configure/write/read `.*` (фактически широкие vhost perms).
- Изоляция: **topic permissions** на `amq.topic`:
  - write: `^dev.{client_id}.*`
  - read: `^srv.{client_id}.*`

Код: `RmqAdminApi` в `app-service/core/integrations/rmq_admin_api.py`.

### 4.3 Org model

- `Org` ↔ `Device` через `DeviceOrgBind` (устройство принадлежит одной org).
- REST: `x-api-key` → `org_id` (`AuthConfig.api_keys`).
- Webhooks: `(org_id, event_type)` → URL.

---

## 5. Proposed architecture (to-be)

### 5.1 Принцип

**Dedicated Integration Exchanges + Platform-owned Per-Tenant Queues.**

Устройства и internal jobs **не** меняются. Platform fan-out’ит нормализованные сообщения в `integration.topic`. Tenant потребляет **только** свои очереди. Команды публикует **только** в `integration.commands`.

```
                 ┌────────────────────── RabbitMQ vhost / ──────────────────────┐
                 │                                                              │
 Device ─MQTT──► │  amq.topic ──► [req/ack/evt/res/out]                         │
                 │       │                                                      │
                 │       │  (platform processing, unchanged)                    │
                 │       ▼                                                      │
                 │  integration.topic  (TOPIC, durable)                         │
                 │       ├─► q.int.<org>.events      bind event.*.<org>.#       │
                 │       ├─► q.int.<org>.snapshots   bind snapshot.<org>.#      │
                 │       ├─► q.int.<org>.status      bind status.<org>.#        │
                 │       ├─► q.int.<org>.tasks       bind task.<org>.#          │
                 │       └─► q.int.<org>.errors      bind error.<org>.#         │
                 │                                                              │
                 │  integration.commands  (TOPIC, durable)                      │
                 │       ▲   RK: cmd.<org>                                      │
                 │       │                                                      │
                 │  platform subscriber ──validate──► DeviceTasksService        │
                 │                           └──► amq.topic srv.<SN>.tsk        │
                 └───────────────────────────┬──────────────────────────────────┘
                                             │ AMQPS
                                             ▼
                                  postamat-domain-service
                                  (user int.<org>)
```

### 5.2 Naming convention (канон)

| Сущность | Шаблон | Пример |
|----------|--------|--------|
| Outbound exchange | `integration.topic` | — |
| Inbound exchange | `integration.commands` | — |
| Tenant user | `int.<org_id>` | `int.42` |
| Tenant queue | `q.int.<org_id>.<channel>` | `q.int.42.events` |
| Outbound RK | `<type>[.<subtype>].<org_id>.<device_sn>` | `event.raw.42.a3b0…` |
| Inbound RK | `cmd.<org_id>` | `cmd.42` |

> В ранних черновиках встречались `q.integration.*` — **отклонено**. Канон: `q.int.*`.

---

## 6. Topology specification

### 6.1 Exchange: `integration.topic`

| Параметр | Значение |
|----------|----------|
| Name | `integration.topic` |
| Type | `topic` |
| Durable | `true` |
| Auto-delete | `false` |
| Internal | `false` |

Публикует **только** platform (service account). Tenant write запрещён.

### 6.2 Exchange: `integration.commands`

| Параметр | Значение |
|----------|----------|
| Name | `integration.commands` |
| Type | **`topic`** (не direct) |
| Durable | `true` |
| Auto-delete | `false` |

**Почему topic, не direct:** topic permissions RabbitMQ применяются к topic-exchange. Для inbound ACL `^cmd\.{org_id}$` exchange **обязан** быть `topic`. Exact routing key `cmd.<org_id>` при этом сохраняется.

Platform объявляет очередь (internal) и bind:

| Queue (platform-owned) | Binding RK | Consumer |
|------------------------|------------|----------|
| `q.int.commands` (или `integration_commands`) | `cmd.*` | app-service subscriber |

Имя внутренней command-очереди платформы **не** обязано следовать `q.int.<org>.*` (это не tenant queue). Рекомендуемое имя: `integration_commands`.

### 6.3 Per-org tenant queues

Создаёт **только платформа** при provision tenant’а (tenant `configure = ^$`).

| Queue | Binding key | Durable | Args |
|-------|-------------|---------|------|
| `q.int.<org>.events` | `event.*.<org>.#` | yes | `x-message-ttl=86400000` (24h) |
| `q.int.<org>.snapshots` | `snapshot.<org>.#` | yes | `x-message-ttl=3600000` (1h) |
| `q.int.<org>.status` | `status.<org>.#` | yes | `x-message-ttl=3600000` (1h) |
| `q.int.<org>.tasks` | `task.<org>.#` | yes | `x-message-ttl=86400000` (24h) |
| `q.int.<org>.errors` | `error.<org>.#` | **no** | `x-message-ttl=3600000` (1h) |

Дополнительно рекомендуется:

- `x-queue-type: classic` (v1; quorum — опционально later);
- единый DLX (optional, v1.1): `integration.dlx` + `q.int.<org>.dlq` — **не обязателен в v1**;
- prefetch на consumer стороне domain-service: настраивается клиентом (рекомендация: 10–50).

### 6.4 Declaration ownership

| Кто | Что declare |
|-----|-------------|
| app-service startup / topology watchdog | `integration.topic`, `integration.commands`, `integration_commands` queue + bind `cmd.*` |
| tenant provision API/job | per-org queues + bindings + RMQ user + permissions |
| tenant user | **ничего** (`configure=^$`) |

---

## 7. Routing keys

### 7.1 Outbound (`integration.topic`)

```
<message_type>.<org_id>.<device_sn>
```

Для событий с подтипом:

```
event.<subtype>.<org_id>.<device_sn>
```

| Routing key | Когда публикуется | Queue channel |
|-------------|-------------------|---------------|
| `event.raw.<org>.<sn>` | Сохранено device event (raw MQTT/body as normalized) | events |
| `event.domain.<org>.<sn>` | Domain interpretation по `event_type_code` (опциональный enrich) | events |
| `snapshot.<org>.<sn>` | Gauge upsert / snapshot state (вкл. type 44) | snapshots |
| `status.<org>.<sn>` | online/offline / connectivity | status |
| `task.<org>.<sn>` | Изменение статуса задачи | tasks |
| `error.<org>.<sn>` | Техошибка обработки, validation reject команды и т.п. | errors |

**Binding notes (RabbitMQ topic):**

- `*` — ровно один dot-segment;
- `#` — zero or more segments;
- `event.*.42.#` матчит `event.raw.42.sn` и `event.domain.42.sn`;
- `task.42.#` матчит `task.42.sn` (и будущие суффиксы).

### 7.2 Inbound (`integration.commands`)

| Routing key | Publisher | Permission |
|-------------|-----------|------------|
| `cmd.<org_id>` | tenant user `int.<org_id>` | topic write `^cmd\.<org_id>$` |

---

## 8. Message envelope

Все сообщения шины — UTF-8 JSON, Content-Type `application/json`.

### 8.1 Common envelope

```json
{
  "version": "1.0",
  "type": "event.raw",
  "timestamp": "2026-08-11T12:00:00Z",
  "org_id": 42,
  "device_sn": "a3b0000000c10221d290825",
  "device_id": 9993,
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {}
}
```

| Поле | Тип | Обязательность | Описание |
|------|-----|----------------|----------|
| `version` | string | yes | Semver envelope; v1 = `"1.0"` |
| `type` | string | yes | См. enum ниже |
| `timestamp` | string (ISO-8601 UTC) | yes | Время публикации platform’ой |
| `org_id` | int | yes | Tenant |
| `device_sn` | string \| null | conditional | SN; null только если не применимо |
| `device_id` | int \| null | conditional | Внутренний id устройства |
| `correlation_id` | string (UUID) | recommended | Трассировка; для cmd/task — **обязателен** |
| `payload` | object | yes | Type-specific |

**`type` enum:**  
`event.raw` | `event.domain` | `snapshot` | `status` | `task` | `error` | `cmd` | `cmd.ack`

AMQP headers (рекомендуемые, дополняют body):

| Header | Значение |
|--------|----------|
| `content_type` | `application/json` |
| `message_id` | UUID (идемпотентность consumer’а) |
| `correlation_id` | дублирует envelope |
| `timestamp` | AMQP timestamp |
| `type` | дублирует envelope.type |
| `x-org-id` | string org_id |
| `x-device-sn` | sn |
| `x-schema-version` | `1.0` |

### 8.2 `event.raw` payload

```json
{
  "event_type_code": 13,
  "dev_event_id": 12345,
  "dev_timestamp": 1723372800,
  "body": { }
}
```

`body` — нормализованное тело device event (как сохранено платформой). Семантика кодов: [`docs/event-types-reference.md`](event-types-reference.md), теги: [`docs/event-property-tags.md`](event-property-tags.md).

### 8.3 `event.domain` payload

Опциональный enrich-слой (может публиковаться **дополнительно** к `event.raw`):

```json
{
  "event_type_code": 13,
  "name": "CellOpenEvent",
  "dev_event_id": 12345,
  "fields": { "304": 5 },
  "raw_ref": { "message_id": "…" }
}
```

### 8.4 `snapshot` payload

```json
{
  "kind": "gauge",
  "event_type_code": 44,
  "gauges": { },
  "updated_at": "2026-08-11T12:00:00Z"
}
```

### 8.5 `status` payload

```json
{
  "online": true,
  "source": "rmq_api_client_action",
  "detail": {}
}
```

### 8.6 `task` payload

```json
{
  "task_id": "uuid",
  "ext_task_id": "order-12345",
  "method_code": 51,
  "status": 3,
  "status_name": "DONE",
  "ttl": 42,
  "priority": 5
}
```

#### Критичный инвариант

> **`status = 3 (DONE)` ≠ физическое исполнение.**  
> DONE означает транспортный/workflow успех задачи (доставка/завершение task machine), но **не** факт механики устройства.  
> Физическое подтверждение — только через `event.*` (например `event_type_code = 13` CellOpenEvent, тег `304`).  
> См. [`docs/task_states.md`](task_states.md), [`docs/1-task-workflow-doc.md`](1-task-workflow-doc.md), [`docs/server-integration-guide.md`](server-integration-guide.md).

Статусы: READY → PENDING → LOCK → DONE | FAILED | EXPIRED | DELETED.  
**TTL = 0 → EXPIRED**, не DONE. См. [`docs/TTL.md`](TTL.md).

### 8.7 `error` payload

```json
{
  "code": "CMD_DEVICE_NOT_IN_ORG",
  "message": "device does not belong to org",
  "retriable": false,
  "cause": {}
}
```

### 8.8 Command (`type=cmd`) — inbound

Публикация tenant’ом в `integration.commands`, RK `cmd.<org_id>`:

```json
{
  "version": "1.0",
  "type": "cmd",
  "timestamp": "2026-08-11T12:00:00Z",
  "org_id": 42,
  "device_sn": "a3b0000000c10221d290825",
  "device_id": null,
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "method_code": 51,
    "ext_task_id": "order-12345",
    "priority": 5,
    "ttl": 60,
    "params": { "dt": [ { "cl": 1 }, { "cl": 2 } ] }
  }
}
```

| Поле | Правила |
|------|---------|
| `org_id` | MUST совпадать с RK и с org из username |
| `device_sn` / `device_id` | Хотя бы одно обязательно |
| `correlation_id` | **MUST** (UUID) |
| `payload.method_code` | MUST, из реестра [`docs/method-codes-reference.md`](method-codes-reference.md) |
| `payload.ext_task_id` | SHOULD (идемпотентность/бизнес-ключ) |
| `payload.ttl` | SHOULD; default platform policy |
| `payload.priority` | OPTIONAL |
| `payload.params` | MUST object — тело задачи устройства (`payload` task API) |

### 8.9 `cmd.ack` (optional outbound)

Платформа **может** публиковать в `integration.topic` (например RK `error.<org>.<sn>` при reject, или отдельный type в tasks/errors):

```json
{
  "type": "cmd.ack",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "accepted": true,
    "task_id": "uuid",
    "ext_task_id": "order-12345"
  }
}
```

**v1 recommendation:**  
- accept → `task.*` со статусом READY/PENDING + optional `cmd.ack`;  
- reject → `error.*` с `correlation_id` исходной команды.  
Синхронный AMQP RPC reply-to — **non-goal v1**.

---

## 9. Command processing pipeline

Platform subscriber на `integration_commands`:

```
1. Parse envelope (JSON, version, type=cmd)
2. Derive org_from_user from RMQ authenticated username: int.<org>
3. Derive org_from_rk from routing key: cmd.<org>
4. Reject unless org_from_user == org_from_rk == envelope.org_id
5. Resolve device by device_sn and/or device_id
6. Reject unless DeviceOrgBind.org_id == org
7. Validate method_code + params (Pydantic schema)
8. DeviceTasksService.create(...)  # existing path
9. Existing MQTT publish path → srv.<SN>.tsk / rsp as today
10. Publish task status updates to integration.topic
11. On failure: publish error.<org>.<sn> with correlation_id
```

**Запрещено:**

- публиковать напрямую в `amq.topic` от имени tenant’а;
- создавать task для device чужой org;
- принимать команду без `correlation_id`.

Correlation data MQTT RPC остаётся внутренней заботой платформы; domain-service опирается на `correlation_id` / `ext_task_id` / `task_id` в integration envelope. См. [`docs/correlation-data-guide.md`](correlation-data-guide.md).

---

## 10. Security model

### 10.1 Tenant user

| Поле | Значение |
|------|----------|
| Username | `int.<org_id>` |
| Password | cryptographically random; Vault / secret manager / one-time REST reveal |
| Tags | `integration` |
| Vhost | `/` |

### 10.2 Vhost permissions

```json
{
  "configure": "^$",
  "write": "^integration\\.commands$",
  "read": "^q\\.int\\.<org_id>\\."
}
```

Смысл:

- **configure `^$`** — нельзя declare/delete queues/exchanges;
- **write** — publish только в `integration.commands`;
- **read** — consume только из своих `q.int.<org_id>.*`.

### 10.3 Topic permissions

**`integration.commands`:**

```json
{
  "exchange": "integration.commands",
  "write": "^cmd\\.<org_id>$",
  "read": "^$"
}
```

**`integration.topic`:**

```json
{
  "exchange": "integration.topic",
  "write": "^$",
  "read": "^$"
}
```

Tenant **не bind’ится** сам к `integration.topic` (нет configure). Доставка — через pre-bound queues; topic read на `integration.topic` tenant’у не нужен.

**`amq.topic` / `amq.direct`:** topic permissions не выдаются; write/read vhost на эти exchanges отсутствует → ACCESS_REFUSED.

### 10.4 Platform service account

Отдельный user (существующий app-service RMQ user) с правами:

- declare topology integration_*;
- publish `integration.topic` (#);
- consume `integration_commands`;
- manage tenant users via RabbitMQ HTTP API (как сегодня `RmqAdminApi` для devices).

### 10.5 Transport

| Требование | v1 |
|------------|----|
| Protocol | AMQP 0-9-1 over TLS (**AMQPS**) |
| TLS | 1.2+ |
| Auth | username/password + TLS (server cert) |
| mTLS client certs for tenants | optional later (рекомендуется для prod hardening) |
| Management UI login for tenants | **запрещён** (no management tag) |

### 10.6 Threat mitigations

| Угроза | Митигация |
|--------|-----------|
| Чтение чужих событий | queue name ACL `q.int.<org>.` + platform-owned bindings |
| Publish команды в чужую org | topic write `^cmd\.<org>$` + app-level triple match |
| Publish в device plane | нет write на `amq.topic` |
| Declare «своей» очереди на `event.#` | configure `^$` |
| Replay password | rotation API; audit log provision/rotate |
| Oversized payload | platform max body size + reject → `error.*` |
| Poison command | validate + non-retriable error; optional DLQ later |

---

## 11. Tenant lifecycle

### 11.1 Provision

Вход: `org_id` (+ optional label).

Шаги (идемпотентно):

1. Generate password; create user `int.<org_id>` tags=`integration`.
2. Set vhost permissions (§10.2).
3. Set topic permissions (§10.3).
4. Declare 5 queues + bindings (§6.3).
5. Store secret reference (not plaintext in DB if possible).
6. Return **one-time** credentials to admin API caller.

### 11.2 Rotate secret

1. Set new password via RMQ API.
2. Invalidate old (RabbitMQ single password model — connections with old pass drop on reconnect).
3. Audit event.

### 11.3 Deprovision / suspend

1. Delete or disable user.
2. Optional: delete queues (policy: retain vs purge — default **retain 24h then delete**).
3. Stop platform publish for org if org disabled at app level.

### 11.4 REST management (future implementation outline)

Базовый путь (предложение): `/api/v1/integration/tenants`

| Method | Path | Описание |
|--------|------|----------|
| PUT | `/api/v1/integration/tenants/{org_id}` | provision / ensure |
| POST | `/api/v1/integration/tenants/{org_id}/rotate` | rotate password |
| DELETE | `/api/v1/integration/tenants/{org_id}` | deprovision |
| GET | `/api/v1/integration/tenants/{org_id}` | status (no password) |

Auth: admin/platform scope (не обычный org api-key) — **открытый вопрос** §18.

---

## 12. Platform publish points

Публикация в `integration.topic` — **side-effect после** успешной основной обработки (best-effort относительно device path: device plane не откатывается из-за сбоя integration publish; сбой логируется + metric).

| Точка | Модуль (as-is) | Outbound type / RK |
|-------|----------------|--------------------|
| New device event | `core/services/device_events_collect.py` → `add()` | `event.raw.<org>.<sn>` (+ optional `event.domain`) |
| Gauge upsert (type 44) | `device_events_collect.py` | `snapshot.<org>.<sn>` |
| Task status transitions | `core/services/device_tasks.py` / task processing | `task.<org>.<sn>` |
| Device online/offline | `core/topologys/internal_bus.py` (`rmq_api_client`) | `status.<org>.<sn>` |
| Command reject / handler errors | integration command subscriber + handlers | `error.<org>.<sn>` |
| Task result related | `fs_queues.result` path / webhook `msg-task-result` analog | `task.<org>.<sn>` (status update) и/или event stream |

**Правила:**

1. Не публиковать integration event для дубликатов device event (`is_new=false`), кроме явных idempotent status snapshots.
2. `org_id` резолвить через `DeviceOrgBind`; если bind отсутствует — `error` в ops log, **не** fan-out в чужие очереди.
3. Webhook publish path **сохраняется** независимо (dual-publish).

---

## 13. Delivery semantics

| Аспект | Контракт v1 |
|--------|-------------|
| Device MQTT plane | без изменений |
| Integration outbound | **at-least-once** |
| Ordering | per-device best-effort; cross-device — нет глобального порядка |
| Idempotency key | AMQP `message_id` + (`dev_event_id` \| `task_id` \| `correlation_id`) |
| Consumer ack | domain-service manual ack after durable handle |
| TTL | queue `x-message-ttl` (§6.3); expired messages dropped |
| Backpressure | native AMQP prefetch; slow consumer → queue growth until TTL |
| Replay | только то, что ещё в очереди (TTL window); out-of-band replay — non-goal v1 |

---

## 14. Observability

Минимальные метрики:

- `integration_publish_total{type,result}`
- `integration_publish_errors_total{type}`
- `integration_cmd_total{result}` (accepted/rejected/error)
- `integration_cmd_reject_total{reason}`
- queue depth gauges для `q.int.*.*` (через RMQ API / exporter)

Логи:

- correlation_id, org_id, device_sn, type, message_id на publish/consume/reject;
- security rejects: отдельный logger/category `integration_security`.

---

## 15. Compatibility

| Компонент | Влияние |
|-----------|---------|
| MQTT device protocol | нет |
| REST `/device-tasks`, `/device-events` | нет |
| Webhooks | остаются; dual-publish |
| Billing counters | без изменений |
| Device RMQ users | без изменений |
| Внешние клиенты REST | без изменений |

Версионирование envelope: поле `version`; несовместимые изменения → `2.0` + параллельная публикация transition period (если понадобится).

---

## 16. Implementation outline (не часть этого RFC-merge как код)

### 16.1 Новые модули (предложение)

| Файл | Назначение |
|------|------------|
| `app-service/core/topologys/integration_bus.py` | declare integration topology + commands subscriber |
| `app-service/core/services/integration_publisher.py` | publish helper (RK + envelope) |
| `app-service/core/services/integration_commands.py` | command pipeline |
| `app-service/core/crud/integration_tenant.py` | tenant lifecycle persistence |
| `app-service/core/schemas/integration.py` | Pydantic envelopes |
| `app-service/api/api_v1/integration.py` | admin REST |
| `app-service/core/config.py` | `IntegrationConfig` |

### 16.2 Изменения существующих

| Файл | Изменение |
|------|-----------|
| `core/topologys/declare.py` | declare integration exchanges / platform command queue |
| `core/services/device_events_collect.py` | publish event/snapshot |
| `core/services/device_tasks.py` (+ processing) | publish task status |
| `core/topologys/internal_bus.py` | publish status |
| `core/integrations/rmq_admin_api.py` | tenant user/permission helpers |
| `create_api_app.py` | register integration subscriber module |

### 16.3 Rollout phases

| Phase | Содержание |
|-------|------------|
| **P0** | RFC review / approve |
| **P1** | Topology + publisher no-op consumers (internal test) |
| **P2** | Tenant provision + ACL security tests |
| **P3** | Wire event/task/status publish points |
| **P4** | Commands subscriber → DeviceTasksService |
| **P5** | Admin REST + docs for domain teams |
| **P6** | Pilot `postamat-domain-service` |

Feature flag: `INTEGRATION_BUS_ENABLED` (default false until P3+).

---

## 17. Test plan

### 17.1 Unit

- RK builders (`event.raw.{org}.{sn}` …).
- Envelope validation (Pydantic).
- Permission payload generation for org_id edge cases (regex escape).
- Command org triple-match logic.

### 17.2 Integration (docker compose)

1. Enable bus; provision org=42.
2. Publish synthetic platform event → message appears in `q.int.42.events`.
3. Snapshot type 44 → `q.int.42.snapshots`.
4. Task status change → `q.int.42.tasks`.
5. Command from `int.42` → task created → device emulator path (optional).

### 17.3 Security

| Кейс | Ожидание |
|------|----------|
| `int.42` basic.get `q.int.99.events` | ACCESS_REFUSED |
| `int.42` publish `amq.topic` / `dev.x.evt` | ACCESS_REFUSED |
| `int.42` publish `integration.commands` RK `cmd.99` | ACCESS_REFUSED (topic) |
| `int.42` publish RK `cmd.42` but body `org_id=99` | app reject + `error.42.*` |
| `int.42` command device of org 99 | reject `CMD_DEVICE_NOT_IN_ORG` |
| `int.42` declare queue | ACCESS_REFUSED |
| `int.42` bind to `integration.topic` | ACCESS_REFUSED |

### 17.4 E2E

`device-emulator` → evt → platform → `q.int.<org>.events` → test consumer ack.

---

## 18. Rejected alternatives

| Вариант | Почему отклонён |
|---------|-----------------|
| Отдельный vhost + shovel/federation | Операционная сложность; двойная топология; harder local dev |
| E2E binding внешних сервисов на `amq.topic` | Смешение device plane; сложные ACL; риск утечки `dev.#` |
| `integration.commands` типа **direct** | Topic permissions не работают на direct → слабее broker-level ACL |
| Только webhooks | Нет backpressure/replay/ack; уже есть и остаётся как HTTP path |
| Kafka / NATS | Лишняя инфра; RabbitMQ уже в core path |
| Per-org exchange | Взрыв объектов; сложнее declare; выигрыш мал при queue-level ACL |
| Tenant-declared queues | Нарушает least privilege; риск bind на `#` |

---

## 19. Open questions

1. **Admin auth** для provision REST: отдельный platform admin key vs org api-key only self-serve?
2. **`cmd.ack`**: обязателен ли в P4 или достаточно `task.*` + `error.*`?
3. **Quorum queues** для `events`/`tasks` в prod?
4. **DLX/DLQ** в v1 или v1.1?
5. **Rate limit** команд per org (broker policy vs app token bucket)?
6. Нужен ли channel `q.int.<org>.results` отдельно от `tasks`, зеркалируя webhook `msg-task-result`?
7. Публиковать ли `event.domain` всегда или по allow-list `event_type_code`?

Рекомендации RFC автора (defaults):

1. platform admin scope для provision;  
2. `task.*` + `error.*` достаточно в v1; `cmd.ack` optional;  
3. classic queues v1;  
4. DLX в v1.1;  
5. app-level rate limit в command handler;  
6. не плодить `results` — status machine в `tasks` + физика в `events`;  
7. `event.domain` по allow-list / feature flag.

---

## 20. References

### Docs

- [`docs/mqtt-rpc-protocol.md`](mqtt-rpc-protocol.md)
- [`docs/mqtt_topic_rules.md`](mqtt_topic_rules.md)
- [`docs/1-task-workflow-doc.md`](1-task-workflow-doc.md)
- [`docs/task_states.md`](task_states.md)
- [`docs/TTL.md`](TTL.md)
- [`docs/3-webhooks.md`](3-webhooks.md)
- [`docs/correlation-data-guide.md`](correlation-data-guide.md)
- [`docs/method-codes-reference.md`](method-codes-reference.md)
- [`docs/event-protocol-mqtt.md`](event-protocol-mqtt.md)
- [`docs/event-types-reference.md`](event-types-reference.md)
- [`docs/server-integration-guide.md`](server-integration-guide.md)
- [`docs/rabbitmq-acl-recovery.md`](rabbitmq-acl-recovery.md)
- [`docs/client-cert-ssl-rmq-config.md`](client-cert-ssl-rmq-config.md)
- [`docs/glossary.md`](glossary.md)

### Code (as-is anchors)

- `app-service/core/topologys/declare.py`
- `app-service/core/topologys/fs_queues.py`
- `app-service/core/topologys/internal_bus.py`
- `app-service/core/integrations/rmq_admin_api.py`
- `app-service/core/integrations/webhooks.py`
- `app-service/core/services/device_events_collect.py`
- `app-service/core/services/device_tasks.py`
- `app-service/core/config.py`
- `app-service/create_api_app.py`

---

## 21. Changelog

| Версия | Дата | Изменение |
|--------|------|-----------|
| 1.0 | 2026-08-11 | Initial Proposed RFC: dedicated integration exchanges, per-org queues, TOPIC commands + ACL, envelope v1 |

---

## Appendix A — Example domain-service consumer (pseudo)

```python
# pseudocode — not production code
async def main(org_id: int, amqps_url: str):
    user = f"int.{org_id}"
    queue = f"q.int.{org_id}.events"
    # connect AMQPS with user/password
    # basic_qos(prefetch_count=20)
    # consume(queue)
    async for msg in consumer:
        env = json.loads(msg.body)
        assert env["org_id"] == org_id
        await handle_event(env)
        await msg.ack()
```

## Appendix B — Example command publish (pseudo)

```python
rk = f"cmd.{org_id}"
body = {
    "version": "1.0",
    "type": "cmd",
    "timestamp": datetime.utcnow().isoformat() + "Z",
    "org_id": org_id,
    "device_sn": sn,
    "device_id": None,
    "correlation_id": str(uuid4()),
    "payload": {
        "method_code": 51,
        "ext_task_id": "order-12345",
        "ttl": 60,
        "params": {"dt": [{"cl": 5}]},
    },
}
await channel.basic_publish(
    body=json.dumps(body).encode(),
    exchange="integration.commands",
    routing_key=rk,
    properties=CommonProperties(content_type="application/json",
                                correlation_id=body["correlation_id"]),
)
# wait for task.* / event.* on tenant queues; do NOT treat task DONE as physical open
```

## Appendix C — Permission templates (org_id=42)

```json
{
  "user": "int.42",
  "vhost": "/",
  "permissions": {
    "configure": "^$",
    "write": "^integration\\.commands$",
    "read": "^q\\.int\\.42\\."
  },
  "topic_permissions": [
    {
      "exchange": "integration.commands",
      "write": "^cmd\\.42$",
      "read": "^$"
    },
    {
      "exchange": "integration.topic",
      "write": "^$",
      "read": "^$"
    }
  ]
}
```
