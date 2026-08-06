# 🖥️ Remote Diagnostics / Live Output Protocol

> **Файл:** `docs/remote-diagnostics-protocol.md`  
> **Версия:** 1.0  
> **Дата:** 2026-08-06  
> **Статус:** спецификация MVP для live logs, stdout/stderr и remote diagnostics через существующий MQTT RPC lifecycle.

---

## 1. Назначение

Remote Diagnostics добавляет единый механизм для:

- live logs с ESP32;
- console-like output;
- stdout/stderr от Linux-agent и Windows-agent;
- диагностических команд из заранее заданного allowlist;
- доставки потока в браузер через цепочку `device → mqtt → backend → websocket → browser`.

Авторизация и владение устройствами остаются в существующей backend-инфраструктуре. Этот протокол не вводит новую модель авторизации: браузерный WebSocket проходит через `nginx-jwt`, где валидируется существующий JWT access-token, а backend дополнительно проверяет принадлежность устройства организации из JWT.

---

## 2. Главные правила

1. **Не добавлять новые server→device топики.** Управление diagnostics/logs идёт только через существующий RPC lifecycle:

   ```text
   srv/<SN>/tsk
   dev/<SN>/req
   srv/<SN>/rsp
   dev/<SN>/res
   ```

2. **Добавить один device→backend топик для потокового вывода:**

   ```text
   dev/<SN>/out
   ```

3. `dev/<SN>/out` — volatile stream. Он не является event, не подтверждается через `eva`, не участвует в event deduplication и не заменяет финальный `dev/<SN>/res`.

4. Remote diagnostics — это не интерактивная shell. Команды передаются как `command_id` из allowlist агента, а не как произвольная shell-строка.

---

## 3. MQTT topics

### Device → Server

| Топик | Назначение |
| :-- | :-- |
| `dev/<SN>/req` | Запрос устройства на получение RPC-задачи |
| `dev/<SN>/res` | Финальный RPC result / метаинформация выполнения |
| `dev/<SN>/evt` | Асинхронное событие устройства |
| `dev/<SN>/ack` | Опциональное подтверждение получения task announcement |
| `dev/<SN>/out` | Volatile потоковый вывод: logs, stdout, stderr, status chunks |

### Server → Device

| Топик | Назначение |
| :-- | :-- |
| `srv/<SN>/tsk` | Анонс новой RPC-задачи |
| `srv/<SN>/rsp` | Тело RPC-задачи |
| `srv/<SN>/eva` | Подтверждение события |
| `srv/<SN>/cmt` | Commit результата RPC |

RabbitMQ routing key для output stream:

```text
dev.<SN>.out
```

Backend MVP подписывается wildcard-binding:

```text
dev.*.out
```

---

## 4. Параметры публикации `dev/<SN>/out`

Рекомендации:

| Сценарий | QoS | retain |
| :-- | :--: | :--: |
| ESP32 live logs | `0` | `false` |
| diagnostic stdout/stderr | `0` или `1` | `false` |
| progress/status | `0` или `1` | `false` |

Если браузерной сессии нет, устройство не должно слать live stream. Backend включает и выключает поток через RPC-команды.

---

## 5. Method codes

Диапазон:

```text
7000..7099 — Remote Diagnostics / Output Streams
```

| method_code | Константа | Назначение |
| ---: | :-- | :-- |
| `7000` | `CMD_DIAG_STREAM_CONTROL` | Start/stop volatile output stream, включая ESP32 live logs |
| `7001` | `CMD_DIAG_EXEC` | Выполнить predefined diagnostic command из allowlist |
| `7002` | `CMD_DIAG_CANCEL` | Отменить активную diagnostic session |

---

## 6. RPC payloads

Все примеры ниже показывают значение `payload.dt`.

### 6.1. Start ESP32 live logs

```json
[
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
```

- `method_code = 7000`
- устройство начинает публиковать logs в `dev/<SN>/out`;
- поток ограничивается `ttl_sec` и, если поддерживается, `max_rate_bps`;
- финальный/стартовый статус возвращается через `dev/<SN>/res`.

### 6.2. Stop ESP32 live logs

```json
[
  {
    "action": "stop",
    "session_id": "8baf0d49-3e35-4210-87a8-111111111111",
    "stream": "esp32-log"
  }
]
```

- `method_code = 7000`

### 6.3. Execute predefined diagnostic command

```json
[
  {
    "session_id": "8baf0d49-3e35-4210-87a8-111111111111",
    "command_id": "system_info",
    "args": {},
    "ttl_sec": 60,
    "max_output_bytes": 1048576,
    "topic": "dev/<SN>/out"
  }
]
```

- `method_code = 7001`
- `command_id` должен существовать в локальном allowlist агента;
- произвольные shell-команды запрещены;
- большой stdout/stderr отправляется в `dev/<SN>/out`;
- финальная метаинформация отправляется в `dev/<SN>/res`.

### 6.4. Cancel diagnostic session

```json
[
  {
    "session_id": "8baf0d49-3e35-4210-87a8-111111111111",
    "reason": "browser_closed"
  }
]
```

- `method_code = 7002`

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

| Поле | Тип | Обязательное | Описание |
| :-- | :-- | :--: | :-- |
| `v` | int | да | Версия envelope |
| `session_id` | string UUID | да | ID browser/diagnostic/log session |
| `seq` | int | да | Монотонный номер chunk внутри session |
| `ts` | string datetime/null | нет | Timestamp на устройстве/агенте |
| `kind` | string | да | `log`, `stdout`, `stderr`, `status`, `result`, `error` |
| `stream` | string | да | Логический stream: `esp32-log`, `stdout`, `stderr`, `system`, `agent` |
| `encoding` | string | да | `utf-8` или `base64` |
| `data` | string | да | Текст или base64 chunk |
| `eof` | bool | нет | Признак завершения stream |
| `exit_code` | int/null | нет | Код завершения diagnostic command |
| `truncated` | bool | нет | Вывод был обрезан по лимиту |

Base64 допускается для бинарных или не-UTF8 данных:

```json
{
  "v": 1,
  "session_id": "8baf0d49-3e35-4210-87a8-111111111111",
  "seq": 43,
  "kind": "stdout",
  "stream": "stdout",
  "encoding": "base64",
  "data": "SGVsbG8NCg==",
  "eof": false
}
```

---

## 8. Финальный RPC result в `dev/<SN>/res`

Большой вывод не отправляется в `/res`. `/res` содержит только итоговую метаинформацию.

Успешный пример:

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

Ошибка:

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

## 9. Backend bridge overview

MVP реализуется внутри `app-service`:

```text
app-service/
  api/api_v1/diagnostics.py
  core/diagnostics/
    schemas.py
    sessions.py
    mqtt_bridge.py
    service.py
    commands.py
```

### WebSocket endpoint

Публичный browser endpoint через `nginx-jwt`:

```text
GET /api/jwt/v1/diagnostics/ws/devices/{sn}
```

Внутренний backend endpoint после rewrite/proxy:

```text
GET /api/v1/diagnostics/ws/devices/{sn}
```

### WebSocket auth и ownership

Для браузерного подключения используется существующий JWT-контур:

1. frontend открывает `wss://dev.leo4.ru/api/jwt/v1/diagnostics/ws/devices/{sn}`;
2. JWT передаётся как cookie `accessToken` — это важно, потому что browser WebSocket API не позволяет надёжно выставлять произвольный `Authorization` header;
3. `nginx-jwt` валидирует JWT (`RS256`) и извлекает claim `orgId`;
4. `nginx-jwt` прокидывает в backend только доверенный заголовок `orgId: <jwt_claim_orgId>`;
5. backend до `websocket.accept()` проверяет, что `{sn}` существует, не удалён и привязан к `orgId`;
6. при отсутствии валидного JWT, отсутствии/невалидном `orgId` или чужом `{sn}` соединение отклоняется (`1008 Policy Violation` на backend-уровне; nginx может вернуть `401/403` до upgrade).

Клиенту запрещено самостоятельно задавать заголовок `orgId`: внешний nginx-конфиг отклоняет такие запросы, чтобы исключить подмену организации.

### Browser → Backend messages

| `type` | Назначение |
| :-- | :-- |
| `start_log` | Создать session и отправить RPC `7000 start` |
| `stop_log` | Отправить RPC `7000 stop` и закрыть live log session |
| `exec` | Создать session и отправить RPC `7001` |
| `cancel` | Отправить RPC `7002` |

### Backend → Browser messages

| `type` | Назначение |
| :-- | :-- |
| `output` | Chunk из `dev/<SN>/out` |
| `status` | Состояние session |
| `error` | Ошибка backend/session/device |

Маршрутизация output chunks выполняется по ключу:

```text
SN + session_id
```

Chunks без активной session дропаются.

---

## 10. Поведение при закрытии браузера

При закрытии WebSocket backend должен:

1. пометить session как closing;
2. для active live log отправить `CMD_DIAG_STREAM_CONTROL stop`;
3. для active diagnostic exec отправить `CMD_DIAG_CANCEL`, если команда ещё выполняется;
4. удалить session из registry;
5. дропать новые chunks с таким `session_id`.

MVP может хранить registry in-memory. Для горизонтального масштабирования потребуется общий session state или sticky routing.

---

## 11. Связанные документы

| Файл | Назначение |
| :-- | :-- |
| [`mqtt_topic_rules.md`](./mqtt_topic_rules.md) | Правила топиков, включая `dev/<SN>/out` |
| [`mqtt-rpc-protocol.md`](./mqtt-rpc-protocol.md) | Базовый RPC lifecycle `tsk`/`req`/`rsp`/`res`/`cmt` |
| [`method-codes-reference.md`](./method-codes-reference.md) | Реестр `method_code`, включая `7000..7002` |
| [`correlation-data-guide.md`](./correlation-data-guide.md) | Correlation Data для RPC-задач |
| [`1-task-workflow-doc.md`](./1-task-workflow-doc.md) | REST workflow задач |

