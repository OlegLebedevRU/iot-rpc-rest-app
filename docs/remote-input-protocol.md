# 🎮 Remote Input Control Plane Protocol (`ctl`, `l4desk`)

> **Файл:** `docs/remote-input-protocol.md`  
> **Версия протокола:** 1 (v1)  
> **Статус:** Alpha (In-Memory State, Single Worker)  
> **Компоненты:** `iot-rpc-rest-app` (FastAPI/FastStream backend), `menubuilder-backend` (BFF/UI), терминальный агент `l4desk.exe`.

---

## 1. Архитектурная схема плоскостей (Plane Separation)

Удалённое управление терминалом разделено на две независимые плоскости:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        Плоскость видео (Media Plane)                   │
│  Терминал (FFmpeg) ─────── SRT / WebRTC / l4media ───────> Браузер     │
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│                     Плоскость управления (Control Plane)               │
│                                                                        │
│  Браузер / MenuBuilder                                                 │
│       │                                                                │
│       │ REST (lease lifecycle) / WebSocket (pointer/click)             │
│       ▼                                                                │
│  iot-rpc-rest-app (app1)                                               │
│       │                                                                │
│       ├── AMQP srv.<SN>.ctl (expiration, QoS 1, non-retained)          │
│       │   ──────> RabbitMQ (amq.topic) ──────> MQTT srv/<SN>/ctl       │
│       │                                                 │              │
│       │                                                 ▼              │
│       │                                          Терминал (l4desk.exe) │
│       │                                                 │              │
│       │   <────── RabbitMQ (q_ctl) <─────────── MQTT dev/<SN>/ctl      │
│       └── AMQP dev.<SN>.ctl (ack, nack, presence)       │              │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

### Принципы изоляции:
1. **Никакого смешивания с RPC**: Remote Input **не** использует очереди и топики `tsk`, `req`, `rsp`, `res`, `cmt`, `rac`.
2. **Никакого сохранения в БД**: События движения мыши, кликов и присутствия **не** сохраняются в PostgreSQL и **не** генерируют записи `DeviceEvent` или `DeviceTask`.
3. **Строгая аренда (Lease)**: В один момент времени управлять терминалом может только один оператор.

---

## 2. MQTT Топики и QoS

| Тип сообщения | Топик MQTT | Routing Key AMQP | Направление | QoS агента | Retain | TTL сервера (`expiration`) |
|---|---|---|---|:---:|:---:|:---:|
| `pointer_move` | `srv/<SN>/ctl` | `srv.<SN>.ctl` | Server → Terminal | 0 | Нет | 2000 мс (`move_ttl_ms`) |
| `mouse_click` | `srv/<SN>/ctl` | `srv.<SN>.ctl` | Server → Terminal | 1 | Нет | 5000 мс (`click_ttl_ms`) |
| `ack` / `nack` | `dev/<SN>/ctl` | `dev.<SN>.ctl` | Terminal → Server | 1 | Нет | — |
| `presence` | `dev/<SN>/ctl` | `dev.<SN>.ctl` | Terminal → Server | 1 | **Да** (retained + LWT) | — |

> **Примечание по доставке в RabbitMQ:** Сервер публикует команды через AMQP-обменник `amq.topic`. RabbitMQ транслирует заголовок `expiration` в MQTT 5 `Message Expiry Interval`. AMQP → MQTT не поддерживает retain, поэтому серверные сообщения не ретейнятся. Retain поддерживается только для публикации `presence` терминалом в Mosquitto/RabbitMQ.

---

## 3. Контракт конвертов v1 (Envelope Specification)

Все сообщения передаются в кодировке UTF-8 JSON с обязательным полем версии `"v": 1`. Ограничение размера: не более 1024 байт для команд сервера и не более 2048 байт для сообщений устройства.

### 3.1. Server → Terminal (`srv/<SN>/ctl`)

#### Перемещение указателя (`pointer_move`):
```json
{
  "v": 1,
  "type": "pointer_move",
  "command_id": "426bc0b9-5df1-4ff2-8d75-beae2f1cae5e",
  "lease_id": "52857e4e-2895-46c0-b2be-5f80b27feea7",
  "sn": "a4b0000773c82116d210826",
  "x": 32768,
  "y": 16384,
  "issued_at_ms": 1788805978123,
  "expires_at_ms": 1788805980123
}
```

#### Нажатие мыши (`mouse_click`):
```json
{
  "v": 1,
  "type": "mouse_click",
  "command_id": "8bb3eb62-8176-46b5-93fa-1a293be46b52",
  "lease_id": "52857e4e-2895-46c0-b2be-5f80b27feea7",
  "sn": "a4b0000773c82116d210826",
  "x": 32768,
  "y": 16384,
  "button": "left",
  "issued_at_ms": 1788805978123,
  "expires_at_ms": 1788805983123
}
```

- Координаты `x`, `y`: нормализованный диапазон `0..65535` виртуального рабочего стола (соответствует Windows Desktop coordinates).
- `button`: в альфа-версии поддерживается только `"left"`.

### 3.2. Terminal → Server (`dev/<SN>/ctl`)

#### Подтверждение успешного ввода (`ack`):
```json
{
  "v": 1,
  "type": "ack",
  "command_id": "8bb3eb62-8176-46b5-93fa-1a293be46b52",
  "lease_id": "52857e4e-2895-46c0-b2be-5f80b27feea7",
  "sn": "a4b0000773c82116d210826",
  "result": "injected",
  "terminal_time_ms": 1788805978301
}
```

#### Ошибка выполнения ввода (`nack`):
```json
{
  "v": 1,
  "type": "nack",
  "command_id": "8bb3eb62-8176-46b5-93fa-1a293be46b52",
  "lease_id": "52857e4e-2895-46c0-b2be-5f80b27feea7",
  "sn": "a4b0000773c82116d210826",
  "code": "interactive_desktop_unavailable",
  "message": "Interactive desktop is locked or inaccessible",
  "terminal_time_ms": 1788805978301
}
```

**Закрытый перечень кодов NACK:**
- `interactive_desktop_unavailable` — сессия Winlogon/UAC/экран заблокирован.
- `lease_invalid` — `lease_id` не совпадает с текущим активным или устарел.
- `expired` — время команды истекло (`terminal_time_ms > expires_at_ms`).
- `duplicate` — повторная команда с тем же `command_id`.
- `invalid_sn` — `sn` в сообщении не совпадает с сертификатом терминала.
- `invalid_payload` — нарушение схемы JSON.
- `unsupported` — неподдерживаемая кнопка или тип команды.
- `inject_failed` — сбой API Windows `SendInput`.

#### Состояние присутствия агента (`presence`):
```json
{
  "v": 1,
  "type": "presence",
  "agent": "l4desk",
  "status": "online",
  "desktop_available": true,
  "screen": {
    "virtual_x": 0,
    "virtual_y": 0,
    "virtual_width": 1920,
    "virtual_height": 1080
  },
  "timestamp": "2026-09-09T00:00:00Z"
}
```
LWT-сообщение offline публикуется брокером при обрыве связи: `{"v":1,"type":"presence","agent":"l4desk","status":"offline","desktop_available":false,"timestamp":"..."}`. Агент подтверждает присутствие каждые 30 секунд. Если сообщение не поступало более 90 секунд (`presence_stale_sec`), статус считается `stale: true`, а агент `online: false`.

---

## 4. Идемпотентность, тайм-ауты и семантика доставки

1. **At-Least-Once & No Retry**: Сервер никогда автоматически не повторяет `mouse_click` при отсутствии ACK во избежание двойных кликов. Если за 5000 мс (`click_ack_timeout_ms`) ACK/NACK не получен, команда помечается результатом `unconfirmed`.
2. **Игнорирование дубликатов**: Если ACK/NACK приходит для уже завершённого или истекшего `command_id`, он логируется в debug и отбрасывается.
3. **Валидация SN**: Сообщения из очереди `ctl`, в которых `payload.sn != SN` из топика/routing key, немедленно отбрасываются с предупреждением в лог.

---

## 5. Модель аренды (Lease Model) и Rate Limiting

1. **Эксклюзивный доступ**: На один терминал (`SN`) может существовать ровно один активный `lease`.
2. **Срок жизни (TTL)**: По умолчанию `lease_ttl_sec = 60` секунд. Продление (`keepalive`) каждые 15 секунд либо автоматически каждым входящим сообщением по WebSocket.
3. **Ограничения частоты (Rate Limits)** на активную аренду:
   - `pointer_move`: не более 10 событий в секунду (`move_rate_per_sec = 10`, алгоритм Token Bucket).
   - `mouse_click`: не более 5 событий в секунду (`click_rate_per_sec = 5`, алгоритм Token Bucket).
   - Превышение частоты: команда отбрасывается, сервер возвращает статус HTTP `429` или WebSocket `WsError(code="rate_limited")`.

---

## 6. Требования к многопоточности и WEB_CONCURRENCY

> ⚠️ **КРИТИЧЕСКОЕ ТРЕБОВАНИЕ АРХИТЕКТУРЫ (ALPHA)**:  
> Реестры аренды (`LeaseRegistry`), отложенных команд (`PendingCommandRegistry`) и присутствия (`PresenceRegistry`) в текущей версии являются **in-memory** структурами одного процесса Python (`asyncio.Lock`).  
> Для корректной работы FastStream consumer и WebSocket-обработчиков сервис **ОБЯЗАН** работать в одном воркере:  
> ```env
> WEB_CONCURRENCY=1
> ```
> При `WEB_CONCURRENCY > 1` входящие ACK/NACK могут обрабатываться другим воркером, вызывая ложные ошибки `unconfirmed` и рассинхронизацию сессий операторов.

При запуске приложения проверяется `settings.gunicorn.workers`. Если значение превышает 1, в лог пишется явное предупреждение `WARNING`.

---

## 7. Roadmap (Планы развития)

1. **[ПРИОРИТЕТ 1] Распределённый State (Redis) — отказ от in-memory**:
   - Вынос реестров `LeaseRegistry`, `PendingCommandRegistry` и `PresenceRegistry` в распределённое хранилище (Redis/KeyDB) на базе существующих интерфейсов `LeaseRegistryProtocol`, `PendingCommandRegistryProtocol`, `PresenceRegistryProtocol`.
   - Поддержка pub/sub шины для синхронизации инвалидации сессий и событий presence между воркерами.
   - Снятие ограничения `WEB_CONCURRENCY=1`, горизонтальное масштабирование приложения до N воркеров и N контейнеров.
2. **Параметры запуска FFmpeg через Control Flow**: Передача параметров кодирования видео и порта стриминга через команды `srv/<SN>/ctl`.
3. **Поддержка правой кнопки мыши и скролла**: Расширение поля `button` (`"right"`, `"middle"`) и добавление типа команды `mouse_scroll`.
