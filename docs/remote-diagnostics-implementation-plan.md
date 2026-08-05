# Remote Diagnostics / Live Output — план внедрения

> Репозиторий: `OlegLebedevRU/iot-rpc-rest-app`  
> Базовая ветка: `master`  
> Цель документа: подготовить изменения в документации и дизайн backend-модуля `/diagnostics` для live logs и remote diagnostics через существующую MQTT/RabbitMQ инфраструктуру.

---

## 1. Контекст

Платформа LEO4 уже использует MQTT 5 поверх RabbitMQ для RPC между backend и устройствами.

Текущий RPC lifecycle:

```text
srv/<SN>/tsk   backend → device: анонс задачи
dev/<SN>/req   device → backend: запрос задачи
srv/<SN>/rsp   backend → device: тело задачи
dev/<SN>/res   device → backend: результат задачи
```

Существующие события:

```text
dev/<SN>/evt   device → backend: асинхронное событие
srv/<SN>/eva   backend → device: подтверждение события
```

Новая задача — добавить единый механизм для:

- live logs с ESP32;
- console-like output;
- stdout/stderr от Linux-agent;
- stdout/stderr от Windows-agent;
- remote diagnostics с ограниченным списком заранее заданных команд;
- доставку потока в браузер через цепочку:

```text
device → mqtt → backend → websocket → browser
```

Инфраструктура авторизации уже существует и должна быть использована. В рамках этой задачи не проектировать авторизацию заново.

---

## 2. Главные архитектурные выводы

### 2.1. Не добавлять новые server→device топики

Нужно минимизировать количество топиков, на которые подписывается устройство, потому что подписки создают очереди/ресурсы на брокере.

Поэтому **не добавлять** отдельные топики вида:

```text
srv/<SN>/ctl
srv/<SN>/cin
srv/<SN>/log
srv/<SN>/diag
```

Управление diagnostics/logs должно идти через существующий RPC lifecycle:

```text
srv/<SN>/tsk
dev/<SN>/req
srv/<SN>/rsp
dev/<SN>/res
```

### 2.2. Добавить один новый device→backend топик для потокового вывода

Добавить единый volatile output topic:

```text
dev/<SN>/out
```

Назначение:

- ESP32 live logs;
- Linux diagnostic stdout/stderr;
- Windows diagnostic stdout/stderr;
- progress/status диагностических команд;
- console-like output;
- будущие типы потокового вывода.

Устройство только **публикует** в `dev/<SN>/out`, но не подписывается на него.

### 2.3. Логи устройства трактовать как консольный вывод

ESP32 logs, Linux stdout, Windows PowerShell output и diagnostic output должны использовать единый envelope.

Это позволяет browser UI отображать всё одинаково:

```text
timestamp + stream + kind + data
```

Например:

```text
[12:34:56] esp32-log INFO WiFi connected
[12:34:57] stdout Filesystem Size Used Avail
[12:34:58] stderr command timeout warning
```

### 2.4. Remote diagnostics вместо полноценной shell

Текущая стратегия — **remote diagnostics с ограниченным списком заранее заданных команд**, а не полноценная интерактивная shell.

Для Linux/Windows могут быть отдельные агенты по аналогии с `examples/`.

Команды должны передаваться как `command_id`, а не как произвольная строка shell-команды.

Пример:

```json
{
  "command_id": "system_info",
  "args": {}
}
```

Не делать так:

```json
{
  "command": "powershell.exe Get-Process | ..."
}
```

---

## 3. Целевая структура MQTT-топиков

### 3.1. Существующие топики остаются

#### Device → Server

```text
dev/<SN>/req
dev/<SN>/res
dev/<SN>/evt
dev/<SN>/ack
```

#### Server → Device

```text
srv/<SN>/tsk
srv/<SN>/rsp
srv/<SN>/eva
```

### 3.2. Новый топик

```text
dev/<SN>/out
```

Где:

- `dev` — направление Device → Server;
- `<SN>` — serial number устройства из CN сертификата;
- `out` — volatile потоковый вывод устройства.

MQTT → RabbitMQ routing key:

```text
dev.<SN>.out
```

Wildcard-подписка backend:

```text
dev/+/out
```

AMQP routing key equivalent:

```text
dev.*.out
```

---

## 4. Семантика `dev/<SN>/out`

`dev/<SN>/out` — это **не** event и **не** RPC result.

Он не должен:

- сохраняться в БД по умолчанию;
- подтверждаться через `srv/<SN>/eva`;
- участвовать в event deduplication;
- заменять финальный `dev/<SN>/res`.

Рекомендуемые параметры публикации:

```text
retain = false
QoS = 0 для live logs
QoS = 0 или 1 для diagnostic stdout/stderr, если нужно повысить надёжность
```

Для ESP32 live logs предпочтительно:

```text
QoS = 0
retain = false
```

Если браузерной сессии нет, устройство не должно слать live stream. Backend включает и выключает поток через RPC-команды.

---

## 5. Method codes для remote diagnostics

Добавить зарезервированный диапазон:

```text
7000..7099 — Remote Diagnostics / Output Streams
```

Минимальный набор:

| method_code | Константа | Назначение |
|---:|---|---|
| `7000` | `CMD_DIAG_STREAM_CONTROL` | Start/stop volatile output stream, включая ESP32 live logs |
| `7001` | `CMD_DIAG_EXEC` | Выполнить predefined diagnostic command из allowlist |
| `7002` | `CMD_DIAG_CANCEL` | Отменить активную diagnostic session |

Эти коды нужно добавить в:

```text
docs/method-codes-reference.md
```

---

## 6. Payload RPC-команд

### 6.1. Start ESP32 live logs

RPC task:

```text
method_code = 7000
```

Payload:

```json
{
  "dt": [
    {
      "action": "start",
      "session_id": "8baf0d49-3e35-4210-87a8-111111111111",
      "stream": "esp32-log",
      "level": "debug",
      "ttl_sec": 300,
      "max_rate_bps": 8192,
      "topic": "dev/<SN>/out"
    }
  ]
}
```

Поведение устройства:

1. Принять RPC-задачу.
2. Начать публикацию логов в `dev/<SN>/out`.
3. Ограничить поток по `ttl_sec`.
4. Ограничить скорость по `max_rate_bps`, если поддерживается.
5. Вернуть финальный/стартовый статус через `dev/<SN>/res`.

### 6.2. Stop ESP32 live logs

```text
method_code = 7000
```

Payload:

```json
{
  "dt": [
    {
      "action": "stop",
      "session_id": "8baf0d49-3e35-4210-87a8-111111111111",
      "stream": "esp32-log"
    }
  ]
}
```

### 6.3. Execute predefined diagnostic command

```text
method_code = 7001
```

Payload:

```json
{
  "dt": [
    {
      "session_id": "8baf0d49-3e35-4210-87a8-111111111111",
      "command_id": "system_info",
      "args": {},
      "ttl_sec": 60,
      "max_output_bytes": 1048576,
      "topic": "dev/<SN>/out"
    }
  ]
}
```

Правила:

- `command_id` должен быть ключом из локального allowlist агента;
- произвольные shell-команды не передавать;
- большой вывод отправлять в `dev/<SN>/out`;
- финальную метаинформацию отправлять в `dev/<SN>/res`.

### 6.4. Cancel diagnostic session

```text
method_code = 7002
```

Payload:

```json
{
  "dt": [
    {
      "session_id": "8baf0d49-3e35-4210-87a8-111111111111",
      "reason": "browser_closed"
    }
  ]
}
```

---

## 7. Output envelope для `dev/<SN>/out`

Единый JSON-envelope:

```json
{
  "v": 1,
  "session_id": "8baf0d49-3e35-4210-87a8-111111111111",
  "seq": 42,
  "ts": "2026-08-05T12:34:56.789Z",
  "kind": "log",
  "stream": "esp32-log",
  "encoding": "utf-8",
  "data": "WiFi connected, ip=192.168.1.10\n",
  "eof": false
}
```

### 7.1. Поля

| Поле | Тип | Обязательное | Описание |
|---|---|:---:|---|
| `v` | int | да | Версия envelope |
| `session_id` | string UUID | да | ID browser/diagnostic/log session |
| `seq` | int | да | Монотонный номер chunk внутри session |
| `ts` | string datetime | желательно | Timestamp на устройстве/агенте |
| `kind` | string | да | Тип вывода: `log`, `stdout`, `stderr`, `status`, `result`, `error` |
| `stream` | string | да | Логический stream: `esp32-log`, `stdout`, `stderr`, `system`, `agent` |
| `encoding` | string | да | `utf-8` или `base64` |
| `data` | string | да | Текст или base64 chunk |
| `eof` | bool | нет | Признак завершения stream |
| `exit_code` | int/null | нет | Код завершения diagnostic command |
| `truncated` | bool | нет | Вывод был обрезан по лимиту |

### 7.2. Пример stdout

```json
{
  "v": 1,
  "session_id": "8baf0d49-3e35-4210-87a8-111111111111",
  "seq": 1,
  "ts": "2026-08-05T12:34:56Z",
  "kind": "stdout",
  "stream": "stdout",
  "encoding": "utf-8",
  "data": "Filesystem      Size  Used Avail Use% Mounted on\n",
  "eof": false
}
```

### 7.3. Пример stderr

```json
{
  "v": 1,
  "session_id": "8baf0d49-3e35-4210-87a8-111111111111",
  "seq": 2,
  "ts": "2026-08-05T12:34:57Z",
  "kind": "stderr",
  "stream": "stderr",
  "encoding": "utf-8",
  "data": "warning: journal contains rotated entries\n",
  "eof": false
}
```

### 7.4. Пример завершения

```json
{
  "v": 1,
  "session_id": "8baf0d49-3e35-4210-87a8-111111111111",
  "seq": 99,
  "ts": "2026-08-05T12:35:01Z",
  "kind": "status",
  "stream": "agent",
  "encoding": "utf-8",
  "data": "completed",
  "eof": true,
  "exit_code": 0,
  "truncated": false
}
```

### 7.5. Base64 для бинарных/не-UTF8 данных

```json
{
  "v": 1,
  "session_id": "8baf0d49-3e35-4210-87a8-111111111111",
  "seq": 43,
  "ts": "2026-08-05T12:34:57.001Z",
  "kind": "stdout",
  "stream": "stdout",
  "encoding": "base64",
  "data": "SGVsbG8NCg==",
  "eof": false
}
```

---

## 8. Финальный RPC result в `dev/<SN>/res`

Большой вывод не должен отправляться в `res`.

`res` содержит только финальную метаинформацию.

Пример успешного результата:

```json
{
  "status": "OK",
  "method_code": 7001,
  "session_id": "8baf0d49-3e35-4210-87a8-111111111111",
  "command_id": "system_info",
  "exit_code": 0,
  "output_topic": "dev/<SN>/out",
  "truncated": false
}
```

Пример ошибки:

```json
{
  "status": "ERROR",
  "method_code": 7001,
  "session_id": "8baf0d49-3e35-4210-87a8-111111111111",
  "command_id": "system_info",
  "exit_code": 1,
  "output_topic": "dev/<SN>/out",
  "error": "timeout",
  "truncated": true
}
```

---

## 9. Backend module `/diagnostics`

### 9.1. Рекомендуемый вариант

На первом этапе реализовать как модуль внутри существующего `app-service`, а не отдельным сервисом.

Причины:

- уже есть FastAPI;
- уже есть доменная модель задач/RPC;
- проще использовать существующую авторизацию;
- проще связать browser session с RPC task;
- меньше инфраструктурных изменений.

Позже модуль можно вынести в отдельный сервис `diagnostics-gateway`, если потоков станет много.

### 9.2. Предлагаемая структура файлов

```text
app-service/
  api/
    diagnostics.py

  core/
    diagnostics/
      __init__.py
      schemas.py
      sessions.py
      mqtt_bridge.py
      service.py
      commands.py
```

Назначение:

| Файл | Назначение |
|---|---|
| `api/diagnostics.py` | WebSocket endpoint для браузера |
| `core/diagnostics/schemas.py` | Pydantic v2 модели browser messages, RPC payloads, output envelope |
| `core/diagnostics/sessions.py` | In-memory registry активных browser/device sessions |
| `core/diagnostics/mqtt_bridge.py` | Consumer `dev/+/out`, маршрутизация chunks в session registry |
| `core/diagnostics/service.py` | Оркестрация start/stop/exec/cancel |
| `core/diagnostics/commands.py` | Реестр допустимых `command_id` на backend-стороне, если нужен для валидации |

---

## 10. Backend WebSocket API

### 10.1. Endpoint

Предлагаемый endpoint:

```text
GET /diagnostics/ws/devices/{sn}
```

или, если в проекте принято группировать WebSocket иначе:

```text
GET /ws/devices/{sn}/diagnostics
```

Нужно выбрать стиль, соответствующий существующим API-конвенциям проекта.

### 10.2. Browser → Backend messages

#### Start live logs

```json
{
  "type": "start_log",
  "level": "debug",
  "ttl_sec": 300
}
```

Backend должен:

1. создать `session_id`;
2. зарегистрировать browser session;
3. создать RPC task `method_code=7000`;
4. отправить start payload устройству;
5. начать проксировать output chunks из `dev/<SN>/out` в WebSocket.

#### Stop live logs

```json
{
  "type": "stop_log",
  "session_id": "8baf0d49-3e35-4210-87a8-111111111111"
}
```

Backend должен:

1. отправить RPC task `method_code=7000`, `action=stop`;
2. закрыть/пометить session;
3. перестать пересылать chunks в browser.

#### Execute diagnostic command

```json
{
  "type": "exec",
  "command_id": "system_info",
  "args": {},
  "ttl_sec": 60
}
```

Backend должен:

1. создать `session_id`;
2. создать RPC task `method_code=7001`;
3. отправить payload устройству;
4. маршрутизировать `dev/<SN>/out` chunks в browser;
5. дождаться `dev/<SN>/res` штатным RPC-механизмом.

#### Cancel diagnostic session

```json
{
  "type": "cancel",
  "session_id": "8baf0d49-3e35-4210-87a8-111111111111"
}
```

Backend должен отправить RPC task `method_code=7002`.

### 10.3. Backend → Browser messages

#### Output chunk

```json
{
  "type": "output",
  "sn": "a3b1234567c10221d290825",
  "session_id": "8baf0d49-3e35-4210-87a8-111111111111",
  "seq": 42,
  "kind": "stdout",
  "stream": "stdout",
  "encoding": "utf-8",
  "data": "Linux device01 6.1.0 ...\n",
  "eof": false
}
```

#### Session status

```json
{
  "type": "status",
  "session_id": "8baf0d49-3e35-4210-87a8-111111111111",
  "status": "started"
}
```

#### Error

```json
{
  "type": "error",
  "session_id": "8baf0d49-3e35-4210-87a8-111111111111",
  "error": "device_not_available"
}
```

---

## 11. Session management

### 11.1. Session identity

Backend должен связывать поток по ключу:

```text
SN + session_id
```

### 11.2. In-memory registry MVP

На MVP допустим in-memory registry:

```text
active_sessions:
  (sn, session_id) -> websocket connection / queue
```

### 11.3. Поведение при закрытии браузера

При закрытии WebSocket:

1. backend помечает session как closing;
2. для active live log отправляет `CMD_DIAG_STREAM_CONTROL stop`;
3. для active diagnostic exec отправляет `CMD_DIAG_CANCEL`, если команда ещё выполняется;
4. удаляет session из registry;
5. новые chunks с таким `session_id` дропает.

### 11.4. Timeout

Каждая session должна иметь TTL.

Рекомендуемые defaults:

```text
live_log ttl_sec: 300
diagnostic_exec ttl_sec: 60
max_output_bytes: 1048576
```

---

## 12. MQTT bridge design

### 12.1. Подписка backend

MVP:

```text
subscribe: dev/+/out
```

RabbitMQ routing key:

```text
dev.*.out
```

Очередь backend consumer:

```text
non-durable
auto-delete or service-scoped
```

Назначение consumer:

1. принимать output envelope;
2. извлекать `SN` из topic/routing key;
3. валидировать payload через Pydantic schema;
4. находить session по `(sn, session_id)`;
5. пересылать chunk в browser;
6. если session не найдена — дропать chunk.

### 12.2. Альтернатива для будущего

Если wildcard-подписка создаст лишний трафик на backend, можно перейти к dynamic subscribe:

```text
dev/<SN>/out
```

только для активных устройств.

Но начинать лучше с `dev/+/out`, потому что ESP32 должен включать поток только при активной browser session.

---

## 13. Browser-side ожидания

Backend должен отдавать поток так, чтобы UI мог:

- показывать live tail;
- хранить только последние N строк;
- не накапливать бесконечный DOM;
- при желании сохранять лог локально.

Рекомендуемые UI defaults:

```text
max_lines: 10000
max_bytes: 20 MB
render_interval: 100-250 ms
drop_policy: drop_oldest
```

Локальное сохранение, если будет реализовываться frontend-часть:

```text
IndexedDB или OPFS
default max_local_size: 100 MB
format: ndjson
```

---

## 14. Изменения в документации

### 14.1. Обновить `docs/mqtt_topic_rules.md`

Добавить `out` в таблицу Device → Server:

```markdown
| `out` | `dev/<SN>/out` | 🖥️ Volatile потоковый вывод устройства: live logs, diagnostic stdout/stderr, agent output |
```

Добавить пояснение:

```markdown
Для remote diagnostics, live logs и ограниченной диагностической консоли не вводятся дополнительные
server→device топики. Управление потоками и диагностическими командами выполняется через существующий
RPC lifecycle (`tsk`/`req`/`rsp`/`res`). Потоковый вывод устройства публикуется в `dev/<SN>/out`.
```

### 14.2. Обновить `docs/method-codes-reference.md`

Добавить диапазон:

```text
7000..7099 — Remote Diagnostics / Output Streams
```

Добавить коды:

```text
7000 CMD_DIAG_STREAM_CONTROL
7001 CMD_DIAG_EXEC
7002 CMD_DIAG_CANCEL
```

Добавить форматы `payload.dt` для каждого кода.

### 14.3. Создать новый документ

Создать:

```text
docs/remote-diagnostics-protocol.md
```

Содержимое:

- назначение;
- топики;
- `dev/<SN>/out`;
- output envelope;
- method codes;
- ESP32 live logs;
- Linux/Windows agent diagnostics;
- RPC result vs streaming output;
- backend bridge overview.

### 14.4. Обновить cross-links

Добавить ссылки на новый документ в:

```text
docs/mqtt_topic_rules.md
docs/mqtt-rpc-protocol.md
docs/method-codes-reference.md
```

---

## 15. Backend implementation phases

### Phase 1 — документация и схемы

1. Обновить `docs/mqtt_topic_rules.md`.
2. Обновить `docs/method-codes-reference.md`.
3. Добавить `docs/remote-diagnostics-protocol.md`.
4. Добавить Pydantic схемы в `app-service/core/diagnostics/schemas.py`.
5. Добавить unit tests для схем.

### Phase 2 — WebSocket session layer

1. Добавить `app-service/api/diagnostics.py`.
2. Добавить WebSocket endpoint.
3. Добавить session registry.
4. Реализовать browser messages:
   - `start_log`;
   - `stop_log`;
   - `exec`;
   - `cancel`.
5. Пока можно мокать отправку RPC task.

### Phase 3 — MQTT output bridge

1. Добавить consumer `dev/+/out`.
2. Валидировать envelope.
3. Маршрутизировать chunks в active WebSocket sessions.
4. Дропать chunks без active session.
5. Добавить tests на routing.

### Phase 4 — RPC integration

1. Реализовать создание RPC tasks для:
   - `7000 start`;
   - `7000 stop`;
   - `7001 exec`;
   - `7002 cancel`.
2. Использовать существующий task workflow.
3. Не ломать существующий RPC lifecycle.
4. Добавить integration tests с mock MQTT/RPC.

### Phase 5 — device examples

Добавить примеры агентов:

```text
examples/linux-diagnostics-agent/
examples/windows-diagnostics-agent/
examples/esp32-log-stream/
```

Если структура examples уже имеет свои конвенции — следовать им.

---

## 16. Pydantic schema draft

Файл:

```text
app-service/core/diagnostics/schemas.py
```

Черновой набор моделей:

```python
from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class OutputKind(StrEnum):
    LOG = "log"
    STDOUT = "stdout"
    STDERR = "stderr"
    STATUS = "status"
    RESULT = "result"
    ERROR = "error"


class OutputEncoding(StrEnum):
    UTF8 = "utf-8"
    BASE64 = "base64"


class DeviceOutputEnvelope(BaseModel):
    v: int = Field(default=1)
    session_id: UUID
    seq: int = Field(ge=0)
    ts: str | None = None
    kind: OutputKind
    stream: str
    encoding: OutputEncoding = OutputEncoding.UTF8
    data: str
    eof: bool = False
    exit_code: int | None = None
    truncated: bool = False


class BrowserMessageType(StrEnum):
    START_LOG = "start_log"
    STOP_LOG = "stop_log"
    EXEC = "exec"
    CANCEL = "cancel"


class BrowserBaseMessage(BaseModel):
    type: BrowserMessageType


class StartLogMessage(BrowserBaseMessage):
    type: BrowserMessageType = BrowserMessageType.START_LOG
    level: str = "info"
    ttl_sec: int = Field(default=300, ge=1, le=3600)


class StopLogMessage(BrowserBaseMessage):
    type: BrowserMessageType = BrowserMessageType.STOP_LOG
    session_id: UUID


class ExecDiagnosticMessage(BrowserBaseMessage):
    type: BrowserMessageType = BrowserMessageType.EXEC
    command_id: str
    args: dict[str, Any] = Field(default_factory=dict)
    ttl_sec: int = Field(default=60, ge=1, le=3600)
    max_output_bytes: int = Field(default=1048576, ge=1)


class CancelDiagnosticMessage(BrowserBaseMessage):
    type: BrowserMessageType = BrowserMessageType.CANCEL
    session_id: UUID
    reason: str | None = None
```

IDE agent should adapt this draft to existing project style.

---

## 17. Tests to add

### 17.1. Documentation consistency tests, if applicable

If the project has doc linting or protocol tests, add checks that:

- `out` is documented in `docs/mqtt_topic_rules.md`;
- method codes `7000`, `7001`, `7002` are documented;
- `docs/remote-diagnostics-protocol.md` exists.

### 17.2. Schema tests

Add tests for:

- valid `DeviceOutputEnvelope`;
- invalid `kind`;
- invalid `encoding`;
- missing `session_id`;
- `seq < 0`;
- base64 envelope accepted as string;
- browser messages validation.

### 17.3. Session routing tests

Test cases:

1. chunk with active `(sn, session_id)` is delivered to WebSocket queue;
2. chunk with unknown session is dropped;
3. chunk with wrong SN is not delivered;
4. session cleanup removes route;
5. closing browser triggers stop/cancel orchestration.

### 17.4. RPC payload tests

Test that service creates expected payloads for:

- `start_log`;
- `stop_log`;
- `exec`;
- `cancel`.

---

## 18. Acceptance criteria

### Documentation

- `docs/mqtt_topic_rules.md` documents `dev/<SN>/out`.
- `docs/method-codes-reference.md` documents `7000..7002`.
- `docs/remote-diagnostics-protocol.md` exists and describes:
  - topic structure;
  - output envelope;
  - start/stop logs;
  - predefined diagnostics;
  - final RPC result;
  - backend bridge.

### Backend design

- There is a clear `/diagnostics` module plan or skeleton.
- WebSocket API is defined.
- Pydantic schemas exist.
- Session routing design exists.
- MQTT bridge design exists.

### Protocol

- No new server→device subscriptions are required.
- Device control remains within existing RPC lifecycle.
- All streaming output uses only:

```text
dev/<SN>/out
```

### ESP32

- Logs are enabled via RPC `7000 start`.
- Logs are disabled via RPC `7000 stop`.
- Log stream uses `dev/<SN>/out`.
- Recommended default is `QoS 0`, `retain=false`.

### Linux/Windows agents

- Diagnostics use `method_code=7001`.
- Commands are predefined by `command_id`.
- Output goes to `dev/<SN>/out`.
- Final metadata goes to `dev/<SN>/res`.

---

## 19. Non-goals for this task

Do not implement in this task:

- full interactive shell;
- arbitrary remote command execution;
- browser direct access to RabbitMQ;
- new authorization model;
- DB persistence for output stream;
- long-term log archive;
- frontend terminal UI beyond backend WebSocket contract;
- manual edits to `uv.lock`.

---

## 20. Recommended implementation order for IDE agent

1. Read:
   - `docs/mqtt_topic_rules.md`
   - `docs/method-codes-reference.md`
   - `docs/mqtt-rpc-protocol.md`
   - `docs/1-task-workflow-doc.md`
   - existing `app-service/api/` structure
   - existing task/RPC creation code

2. Apply documentation changes:
   - add `out`;
   - add `7000..7002`;
   - add `remote-diagnostics-protocol.md`;
   - add cross-links.

3. Add backend skeleton:
   - `app-service/core/diagnostics/schemas.py`;
   - `app-service/core/diagnostics/sessions.py`;
   - `app-service/core/diagnostics/service.py`;
   - `app-service/core/diagnostics/mqtt_bridge.py`;
   - `app-service/api/diagnostics.py`.

4. Add tests for schemas and session routing.

5. Keep implementation async-first.

6. Run:

```bash
uv run pytest
uv run ruff check .
uv run black --check .
```

7. If formatting needed:

```bash
uv run black .
```

---

## 21. Summary

Target protocol:

```text
Control:
  existing MQTT RPC only

Streaming output:
  dev/<SN>/out only

ESP32:
  RPC 7000 start/stop logs
  logs → dev/<SN>/out

Linux/Windows:
  RPC 7001 predefined diagnostics
  stdout/stderr → dev/<SN>/out
  final metadata → dev/<SN>/res

Cancel:
  RPC 7002

Backend:
  app-service diagnostics module
  WebSocket browser bridge
  one MQTT consumer on dev/+/out
  route by SN + session_id
```