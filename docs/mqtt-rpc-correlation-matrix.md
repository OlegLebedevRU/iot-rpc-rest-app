# MQTT RPC Correlation Matrix

Краткая сводка по тому, где и как передаётся `correlationData` / `correlation_id` в протоколе и в текущей реализации.

> 🧩 Правила корреляции являются транспортно-общими и одинаково применяются ко всем документированным вариантам совместимости устройств: `Platerra`, `Siplite`, `l4-hmi`.
> 📘 Матрица совместимости `method_code` и форматы `payload.dt` вынесены в [`method-codes-reference.md`](./method-codes-reference.md).

Основа:
- протокол: `docs/mqtt-rpc-protocol.md`
- серверная реализация: `app-service/core/services/device_task_processing.py`, `app-service/core/topologys/fs_depends.py`, `app-service/core/topologys/fs_queues.py`
- клиентская реализация: `examples/c-win-clion-rpc-client/src/device_client.c`

---

## Основной вывод

Источник истины для correlation по протоколу:

1. MQTT v5 `CorrelationData`
2. User Property `correlationData`
3. реализационные fallback-механизмы

В текущей реализации дополнительно используются transport fallback-поля в `payload/body`, потому что на пути `MQTT -> RabbitMQ -> AMQP -> FastStream` inbound metadata от device может теряться.

---

## Матрица по RPC-сообщениям

| Сообщение | Направление | Correlation по протоколу | Correlation в текущей реализации | Обязательность по протоколу | Комментарий |
|---|---|---|---|---|---|
| `tsk` | `srv/<SN>/tsk` | Да, через `CorrelationData`; допускается дублирование в `correlationData` | 1) `correlation_id` -> MQTT `CorrelationData`; 2) header / User Property `correlationData`; 3) в payload есть `id`, который обычно совпадает с task id/correlation | Да | `payload.id` не является обязательным носителем correlation по протоколу, но в текущем коде совпадает с task/correlation id |
| `ack` | `dev/<SN>/ack` | Да, если `ack` используется | 1) MQTT `CorrelationData`; 2) User Property `correlationData`; 3) body fallback: `{"correlationData":"<uuid>"}` | Нет, `ack` опционален | Для server-trigger flow `ack` допустимо пропустить и сразу перейти к `req` |
| `req` | `dev/<SN>/req` | Да, обязательно | 1) MQTT `CorrelationData`; 2) User Property `correlationData`; 3) body fallback: `{"correlationData":"<uuid>"}` | Да | Для polling используется `UUID(0)`; для trigger и выбранной задачи — конкретный task UUID |
| `rsp` | `srv/<SN>/rsp` | Да, через `CorrelationData`; допускается `correlationData` в user properties | 1) `correlation_id` -> MQTT `CorrelationData`; 2) header / User Property `correlationData`; 3) payload содержит `id`, который в текущей реализации дублирует task/correlation id | Да | `payload.id` — реализационный дубль, а не обязательная часть протокола |
| `res` | `dev/<SN>/res` | Да, обязательно | 1) MQTT `CorrelationData`; 2) User Property `correlationData`; 3) body fallback: `{"corr_data":"<uuid>","result":...}` | Да | Сервер умеет извлекать correlation из body fallback, если metadata теряется |
| `cmt` | `srv/<SN>/cmt` | Да, через `CorrelationData`; `result_id` отдельным user property | 1) `correlation_id` -> MQTT `CorrelationData`; 2) header / User Property `correlationData`; 3) `result_id` в headers/user properties | Да | `result_id` не является correlation, это ID сохранённого результата |

---

## Дополнение по `evt` / `eva`

| Сообщение | Направление | Correlation по протоколу | Реализация | Комментарий |
|---|---|---|---|---|
| `evt` | `dev/<SN>/evt` | Да, отдельный новый UUID на каждое событие | Клиент публикует новый UUID как `CorrelationData` и user properties событий (`event_type_code`, `dev_event_id`, `dev_timestamp`) | Не связано с RPC lifecycle |
| `eva` | `srv/<SN>/eva` | Да, тот же UUID, что у `evt` | `correlation_id` → MQTT `CorrelationData`; headers: `event_type_code`, `dev_event_id`, `correlationData`; payload: `{"status": "success"\|"error"}` | Подтверждение обработки события; отправляется и для новых, и для идемпотентных дубликатов; TTL = 180 сек |

### Идемпотентность событий

Дубликаты `evt` определяются по уникальному индексу `(device_id, dev_event_id, dev_timestamp)` при `dev_event_id != 0`:

- **Новое событие** → сохраняется, публикуется вебхук, отправляется EVA `"success"`
- **Дубликат** → не сохраняется повторно, вебхук не публикуется, но EVA `"success"` всё равно отправляется

### Условия отправки EVA

EVA отправляется при выполнении всех условий:
- `event_type_code` задан и ≠ 0
- `event_type_code` не является gauge-типом
- `dev_event_id` задан и ≠ 0

---

## Что именно предусмотрено протоколом

Для RPC протокол требует correlation в metadata сообщения:

- MQTT v5 `CorrelationData`
- либо совместимый fallback через User Property `correlationData`

Протокол **не требует** передавать correlation в payload-полях вроде:

- `payload.id`
- `payload.correlationData`
- `payload.corr_data`

Эти поля относятся к особенностям реализации или к transport fallback.

---

## Что является особенностью текущей реализации

### 1. `RSP.payload.id`
В `rsp` payload есть поле `id`, которое в текущем коде совпадает с `task.id`, а `task.id` одновременно используется как correlation id.

То есть:
- в реализации `RSP.id` фактически дублирует correlation
- в протоколе это не основной и не обязательный способ передачи correlation

### 2. Body fallback для inbound сообщений от device
Из-за того, что inbound MQTT metadata от device может теряться в мосте MQTT/AMQP, были добавлены fallback-поля в body:

- `req` / `ack`:
  - `{"correlationData":"<uuid>"}`
- `res`:
  - `{"corr_data":"<uuid>","result":...}`

Серверный extractor учитывает body fallback после проверки headers и перед fallback на случайный `msg.correlation_id`.

### 3. `UUID(0)`
`00000000-0000-0000-0000-000000000000` используется только для polling:

- `req(UUID0)` от device
- `rsp(method_code=0, UUID0)` как `NOP`

Он не должен использоваться для `res` и не должен переводить реальные задачи в статусы.

---

## Где correlation передаётся фактически

### Server -> Device
- `tsk`: `correlation_id` + `headers["correlationData"]`
- `rsp`: `correlation_id` + `headers["correlationData"]`
- `cmt`: `correlation_id` + `headers["correlationData"]`

### Device -> Server
- `ack`: `CorrelationData` + User Property `correlationData` + body fallback
- `req`: `CorrelationData` + User Property `correlationData` + body fallback
- `res`: `CorrelationData` + User Property `correlationData` + body fallback (`corr_data`)

---

## Практический вывод

### Что использовать как primary source
Для обработки correlation нужно считать приоритетным:

1. `CorrelationData`
2. `correlationData` user property
3. body fallback (`correlationData`, `corr_data`, и т.д.)

### Что считать только дублирующим полем
- `RSP.payload.id`

Его можно использовать как дополнительную проверку консистентности, но не как основной carrier correlation по протоколу.

---

## Короткий ответ на практический вопрос

### Дублирует ли `RSP.id` correlation?
Да, в текущей реализации — да.

### Предусмотрено ли это протоколом?
Нет, как обязательный carrier correlation — нет.

### Где ещё передаётся correlation?
- MQTT `CorrelationData`
- User Property `correlationData`
- body fallback в `ack/req/res`
- косвенно — `RSP.payload.id`, но это реализационный дубль, а не часть обязательного протокола.

---

## Связанные документы

- [`docs/correlation-data-guide.md`](./correlation-data-guide.md) — Подробное руководство по Correlation Data: форматы, fallback, рекомендации для клиентов
- [`docs/mqtt-rpc-protocol.md`](./mqtt-rpc-protocol.md) — Полная спецификация RPC-протокола
- [`docs/event-protocol-mqtt.md`](./event-protocol-mqtt.md) — Протокол событий EVT/EVA
