# Архитектурный обзор: Remote Diagnostics

> Статус: реализовано (MVP), in-memory session registry, без UI-консоли на бэкенде.

---

## 1. Назначение подсистемы

Remote Diagnostics обеспечивает:
- **Live logs** с ESP32-устройств
- **Predefined diagnostic commands** (21 команда: system_info, disk_usage, process_list и т.д.)
- **Console-like output** (stdout/stderr) от Linux/Windows агентов
- Доставку потока в браузер через цепочку: `device -> MQTT -> backend -> WebSocket -> browser`

Управление устройством идёт через существующий MQTT RPC lifecycle (без новых server->device топиков). Единственный новый топик — `dev/<SN>/out` для потокового вывода.

---

## 2. Файловая структура

### Core модуль (`app-service/core/diagnostics/`)

| Файл | Строки | Назначение |
|------|-------:|------------|
| `__init__.py` | 1 | Package marker |
| `commands.py` | 124 | Method codes (7000-7002), allowlist из 21 команды, константы TTL/лимитов |
| `schemas.py` | 287 | Все Pydantic v2 модели: envelope, browser messages, RPC payloads, backend messages, builder-функции |
| `sessions.py` | 111 | `DiagnosticSession` dataclass + `DiagnosticsSessionRegistry` (in-memory, thread-safe через asyncio.Lock) |
| `service.py` | 206 | `DiagnosticService` (оркестрация start/stop/exec/cancel), `DiagnosticTaskSender` Protocol, `DeviceTaskDiagnosticTaskSender` (интеграция с DeviceTasksService) |
| `mqtt_bridge.py` | 61 | Парсинг routing key `dev.<SN>.out`, валидация `DeviceOutputEnvelope`, маршрутизация в session registry |

### API слой

| Файл | Строки | Назначение |
|------|-------:|------------|
| `api/api_v1/diagnostics.py` | 185 | WebSocket endpoint `/ws/devices/{sn}`, auth (superuser + org_id + device ownership), message dispatch, queue forwarding |
| `api/api_v1/__init__.py` | 31 | Регистрация `diagnostics_router` в v1 router (строка 30) |

### Topology / MQ

| Файл | Строка | Назначение |
|------|-------:|------------|
| `core/topologys/declare.py` | 51-52 | Объявление `q_out` — non-durable очередь, binding `dev.*.out` к `amq.topic` |
| `core/topologys/fs_queues.py` | 157-163 | FastStream subscriber `diagnostics_output` на `q_out` -> `handle_device_output_message()` |

### Конфигурация

| Файл | Строка | Назначение |
|------|-------:|------------|
| `core/config.py` | 77 | `ApiV1Prefix.diagnostics = "/diagnostics"` |
| `config/tags.py` | 92-104 | OpenAPI tag "Diagnostics" с описанием |

### Инфраструктура

| Файл | Назначение |
|------|------------|
| `nginx-configs/dev_leo4_ru/default.conf` | WebSocket proxy `/api/v1/diagnostics/` с 3600s timeout |

### Тесты

| Файл | Строки | Покрытие |
|------|-------:|----------|
| `tests/api/v1/test_diagnostics_ws_auth.py` | 109 | Auth: org_id resolution, superuser check, device ownership, rejection flows |
| `tests/core/diagnostics/test_schemas.py` | 156 | Валидация envelope, browser messages, RPC payload builders |
| `tests/core/diagnostics/test_sessions.py` | 119 | Session routing: delivery, drop unknown, wrong SN, cleanup |
| `tests/core/diagnostics/test_mqtt_bridge.py` | 81 | Routing key parsing, payload validation, routing to registry |
| `tests/core/diagnostics/test_service.py` | 233 | Service orchestration: start/stop/exec/cancel, command validation, DeviceTaskDiagnosticTaskSender |

### Документация

| Файл | Назначение |
|------|------------|
| `docs/remote-diagnostics-protocol.md` | Полная спецификация протокола |
| `docs/remote-diagnostics-implementation-plan.md` | План внедрения (1161 строка) |
| `docs/method-codes-reference.md` | Реестр method codes 7000-7002 |
| `docs/mqtt_topic_rules.md` | Правила топиков, включая `dev/<SN>/out` |

---

## 3. Data Flow

### 3.1. Start Live Log (browser -> device -> browser)

```
Browser                    Backend                         Device
  |                          |                               |
  |-- WS: start_log -------->|                               |
  |                          |                               |
  |                          |-- create session (UUID)       |
  |                          |-- register in registry        |
  |                          |                               |
  |                          |-- DB: create RPC task -------->| MQTT: srv/<SN>/tsk
  |                          |   method_code=7000            |
  |                          |   action=start                |
  |                          |   session_id, stream, level   |
  |                          |   ttl_sec, max_rate_bps       |
  |                          |   topic=dev/<SN>/out          |
  |                          |                               |
  |<-- WS: status=started ---|                               |
  |                          |                               |
  |                          |<-- MQTT: dev/<SN>/out --------| device publishes logs
  |                          |   DeviceOutputEnvelope        |
  |                          |   (v, session_id, seq,        |
  |                          |    kind=log, data=...)        |
  |                          |                               |
  |                          | parse routing_key -> SN       |
  |                          | validate envelope (Pydantic)  |
  |                          | route by (SN, session_id)     |
  |                          | -> session.queue.put()        |
  |                          |                               |
  |<-- WS: output message ---|   _forward_session_queue()    |
  |    {type:"output",       |   reads from queue            |
  |     sn, session_id,      |   sends_json to WS            |
  |     seq, kind, data...}  |                               |
  |                          |                               |
  |                          |<-- MQTT: dev/<SN>/res --------| final status (optional)
  |                          |                               |
```

### 3.2. Execute Diagnostic Command

```
Browser                    Backend                         Device
  |                          |                               |
  |-- WS: exec ------------->|                               |
  |   {command_id, args,     |                               |
  |    ttl_sec, max_output}  |                               |
  |                          |                               |
  |                          |-- validate command_id         |
  |                          |   (is_known_command)          |
  |                          |-- create session (EXEC kind)  |
  |                          |-- register in registry        |
  |                          |                               |
  |                          |-- DB: create RPC task -------->| MQTT: srv/<SN>/tsk
  |                          |   method_code=7001            |
  |                          |   command_id, args, ttl       |
  |                          |   topic=dev/<SN>/out          |
  |                          |                               |
  |<-- WS: status=started ---|                               |
  |                          |                               |
  |                          |<-- MQTT: dev/<SN>/out --------| stdout/stderr chunks
  |<-- WS: output (N msgs) -|   (kind=stdout/stderr)        |
  |                          |                               |
  |                          |<-- MQTT: dev/<SN>/res --------| final: exit_code, truncated
  |<-- WS: output (eof) ----|   (kind=status, eof=true)     |
```

### 3.3. Stop / Cancel

```
Browser                    Backend                         Device
  |                          |                               |
  |-- WS: stop_log --------->|                               |
  |   {session_id}           |                               |
  |                          |-- mark_closing(session_id)    |
  |                          |-- DB: create RPC task -------->| MQTT: srv/<SN>/tsk
  |                          |   method_code=7000            |
  |                          |   action=stop                 |
  |                          |-- remove from registry        |
  |                          |-- cancel forwarder task       |
  |                          |                               |
  |-- WS: cancel ----------->|                               |
  |   {session_id, reason}   |                               |
  |                          |-- mark_closing(session_id)    |
  |                          |-- DB: create RPC task -------->| MQTT: srv/<SN>/tsk
  |                          |   method_code=7002            |
  |                          |-- remove from registry        |
```

### 3.4. Browser Disconnect Cleanup

```
WebSocket closed (WebSocketDisconnect)
  |
  +-- for each active forwarder:
  |     task.cancel()
  |     service.close_session(sn, session_id)
  |       |-- mark_closing
  |       |-- if LIVE_LOG: send stop (7000)
  |       |-- if EXEC: send cancel (7002)
  |       |-- remove from registry
  |
  +-- gather all cancelled forwarders
```

---

## 4. Контракты

### 4.1. MQTT Topics

| Направление | Топик | Routing Key | Назначение |
|-------------|-------|-------------|------------|
| Device -> Backend | `dev/<SN>/out` | `dev.<SN>.out` | Volatile streaming output (logs, stdout, stderr) |
| Backend -> Device | `srv/<SN>/tsk` | (existing) | RPC task announcement |
| Device -> Backend | `dev/<SN>/req` | (existing) | Device requests task body |
| Backend -> Device | `srv/<SN>/rsp` | (existing) | RPC task body |
| Device -> Backend | `dev/<SN>/res` | (existing) | Final RPC result |

Очередь `q_out`: **non-durable**, binding `dev.*.out` к `amq.topic`.

### 4.2. Method Codes

| Code | Константа | Назначение |
|-----:|-----------|------------|
| 7000 | `CMD_DIAG_STREAM_CONTROL` | Start/stop volatile output stream |
| 7001 | `CMD_DIAG_EXEC` | Execute predefined diagnostic command |
| 7002 | `CMD_DIAG_CANCEL` | Cancel active diagnostic session |

Диапазон `7000..7099` зарезервирован для diagnostics.

### 4.3. Device Output Envelope (`dev/<SN>/out`)

```python
class DeviceOutputEnvelope(BaseModel):
    v: int = 1                    # версия envelope
    session_id: UUID              # ID сессии
    seq: int >= 0                 # монотонный номер chunk
    ts: str | None                # timestamp на устройстве
    kind: OutputKind              # log | stdout | stderr | status | result | error
    stream: str                   # esp32-log | stdout | stderr | system | agent
    encoding: OutputEncoding      # utf-8 | base64
    data: str                     # текст или base64 chunk
    eof: bool = False             # признак завершения
    exit_code: int | None         # код завершения команды
    truncated: bool = False       # вывод обрезан по лимиту
```

### 4.4. Browser -> Backend (WebSocket)

Discriminated union по полю `type`:

| type | Схема | Поля |
|------|-------|------|
| `start_log` | `StartLogMessage` | level, stream, ttl_sec, max_rate_bps |
| `stop_log` | `StopLogMessage` | session_id, stream |
| `exec` | `ExecDiagnosticMessage` | command_id, args, ttl_sec, max_output_bytes |
| `cancel` | `CancelDiagnosticMessage` | session_id, reason |

### 4.5. Backend -> Browser (WebSocket)

| type | Схема | Поля |
|------|-------|------|
| `output` | `BackendOutputMessage` | sn, session_id, seq, ts, kind, stream, encoding, data, eof, exit_code, truncated |
| `status` | `BackendStatusMessage` | session_id, status |
| `error` | `BackendErrorMessage` | session_id?, error |

### 4.6. RPC Payloads (backend -> device)

| Method | Схема | Ключевые поля |
|--------|-------|---------------|
| 7000 | `DiagStreamControlPayload` | action (start/stop), session_id, stream, level?, ttl_sec?, max_rate_bps?, topic? |
| 7001 | `DiagExecPayload` | session_id, command_id, args, ttl_sec, max_output_bytes, topic |
| 7002 | `DiagCancelPayload` | session_id, reason? |

Обёртка: `DiagnosticRpcPayload.dt: list[...]` -> `DiagnosticRpcTask(method_code, payload)`.

### 4.7. DiagnosticTaskSender Protocol

```python
class DiagnosticTaskSender(Protocol):
    async def send(self, sn: str, task: DiagnosticRpcTask) -> None: ...
```

Реализация `DeviceTaskDiagnosticTaskSender`:
- Получает `device_id` через `DeviceRepo.get_device_id(session, sn, org_id)`
- Создаёт `TaskCreate` с `ext_task_id = "diagnostics:{session_id}:{method_code}:{suffix}"`
- Вызывает `DeviceTasksService(session, org_id).create(task_create)`

---

## 5. Архитектурные слои и зависимости

```
┌─────────────────────────────────────────────────────────────┐
│  Browser (WSS через nginx-jwt)                              │
│  /api/jwt/v1/diagnostics/ws/devices/{sn}                    │
└──────────────────────┬──────────────────────────────────────┘
                       │ WebSocket
┌──────────────────────▼──────────────────────────────────────┐
│  API Layer: api/api_v1/diagnostics.py                       │
│  - _resolve_websocket_org_id()  (auth: X-Role, orgId)       │
│  - _is_websocket_device_allowed()  (DeviceRepo check)       │
│  - diagnostics_ws()  (main WS handler loop)                 │
│  - _forward_session_queue()  (async queue -> WS forwarder)  │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│  Service Layer: core/diagnostics/service.py                 │
│  DiagnosticService                                          │
│  - start_log(sn, msg) -> session                            │
│  - stop_log(sn, msg) -> bool                                │
│  - exec(sn, msg) -> session                                 │
│  - cancel(sn, msg) -> bool                                  │
│  - close_session(sn, session_id) -> bool                    │
│  - emit_status(session, status)                             │
│  - emit_error(session, error)                               │
│                                                              │
│  DiagnosticTaskSender (Protocol)                            │
│  └─ DeviceTaskDiagnosticTaskSender                          │
│     -> DeviceTasksService.create(TaskCreate)                │
└───────┬──────────────────────────────────┬──────────────────┘
        │                                  │
┌───────▼───────────┐          ┌───────────▼──────────────────┐
│ Session Registry  │          │  DeviceTasksService          │
│ sessions.py       │          │  (existing RPC lifecycle)    │
│                   │          │  -> MQTT: srv/<SN>/tsk       │
│ DiagnosticSession │          │  -> DB: tb_dev_tasks         │
│  .queue (asyncio) │          └──────────────────────────────┘
│  .sn, .session_id │
│  .kind, .ttl_sec  │
│  .closing         │
│                   │
│ DiagnosticsSession│
│  Registry         │
│  .register()      │
│  .get()           │
│  .route_output()  │
│  .mark_closing()  │
│  .remove()        │
│  .cleanup_expired│
└───────▲───────────┘
        │
┌───────┴─────────────────────────────────────────────────────┐
│  MQTT Bridge: core/diagnostics/mqtt_bridge.py               │
│  - extract_sn_from_output_routing_key(routing_key)          │
│  - decode_output_payload(payload) -> DeviceOutputEnvelope   │
│  - handle_device_output_message(routing_key, payload)       │
│    -> session_registry.route_output(sn, envelope)           │
└───────▲─────────────────────────────────────────────────────┘
        │
┌───────┴─────────────────────────────────────────────────────┐
│  FastStream Subscriber: core/topologys/fs_queues.py:157     │
│  @fs_router.subscriber(q_out)                               │
│  async def diagnostics_output(msg, sn):                     │
│    -> handle_device_output_message(routing_key, payload)    │
└───────▲─────────────────────────────────────────────────────┘
        │
┌───────┴─────────────────────────────────────────────────────┐
│  RabbitMQ                                                   │
│  Queue: q_out (non-durable, binding dev.*.out)              │
│  Exchange: amq.topic                                        │
│  Device publishes to: dev/<SN>/out via MQTT                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. Auth Flow

```
Browser
  │
  │  WSS /api/jwt/v1/diagnostics/ws/devices/{sn}
  │  Cookie: accessToken (JWT RS256)
  │
  ▼
nginx-jwt
  │  validates JWT, extracts orgId claim
  │  forwards trusted headers: X-Role, X-Role-Id, X-User-Id, orgId
  │  strips client-supplied orgId (anti-spoofing)
  │
  ▼
Backend: _resolve_websocket_org_id()
  │  checks superuser/admin role
  │  reads org_id from query param or trusted header
  │  returns None if not authorized -> WS 1008
  │
  ▼
Backend: _is_websocket_device_allowed()
  │  DeviceRepo.get_device_id(session, sn, org_id)
  │  returns False if device not in org -> WS 1008
  │
  ▼
websocket.accept() -> enter message loop
```

---

## 7. Predefined Commands (21 штука)

| Категория | command_id | Описание |
|-----------|------------|----------|
| Cross-platform | `system_info` | OS, kernel/firmware, hardware summary |
| | `echo` | Echo args; connectivity/latency check |
| | `time` | Current device clock |
| Universal | `network_info` | Interfaces, routes, DNS |
| | `disk_usage` | Filesystem usage |
| | `service_status` | Agent/service status |
| Linux | `uptime` | Uptime + load average |
| | `memory_usage` | RAM/swap stats |
| | `process_list` | Full process snapshot |
| | `top_processes` | Top CPU/memory processes |
| | `journal_logs` | Recent systemd journal |
| | `iptables_rules` | Firewall rules |
| | `systemctl_status` | Systemd unit status |
| Windows | `get_processes` | Process list |
| | `get_services` | Service list + states |
| | `event_log` | Event Log entries |
| | `disk_info` | Disk partitions/volumes |
| | `cpu_usage` | CPU snapshot |
| | `network_config` | Adapter config (ipconfig) |
| | `os_version` | OS version/build info |
| | `mssql_query` | Predefined MSSQL query |
| Utility | `list_commands` | Agent's supported command_ids |

---

## 8. UI Console

**В бэкенде нет UI-консоли.** Frontend для diagnostics WebSocket строится отдельно и подключается к:

```
wss://dev.leo4.ru/api/jwt/v1/diagnostics/ws/devices/{sn}
```

Рекомендации для UI (из протокола):
- Live tail с render interval 100-250ms
- Хранить последние N строк (max_lines: 10000)
- Drop policy: drop_oldest
- Локальное сохранение: IndexedDB/OPFS, max 100MB, ndjson

В проекте есть `pages/` (FastUI) но он не содержит diagnostics UI. Swagger UI доступен на `/docs` с тегом "Diagnostics".

---

## 9. Ключевые инварианты

1. **Нет новых server->device топиков** — управление через существующий RPC lifecycle
2. **`dev/<SN>/out` — volatile** — не сохраняется в БД, не подтверждается через `eva`, retain=false
3. **In-memory registry** — не переживает рестарт backend; для масштабирования нужен sticky routing или shared state
4. **Session routing по (SN, session_id)** — chunks без активной сессии дропаются
5. **Superuser-only** — WebSocket доступен только для admin/superuser ролей
6. **Command allowlist** — произвольные shell-команды запрещены, только `command_id` из `DIAGNOSTIC_COMMANDS`
7. **ext_task_id формат** — `"diagnostics:{session_id}:{method_code}:{suffix}"` для идентификации в device_tasks
