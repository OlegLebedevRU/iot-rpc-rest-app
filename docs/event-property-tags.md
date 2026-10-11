# 🔢 События · Реестр тегов

> Числовые свойства объектов массива `300`. Структура payload зависит от типа события.

[← Документация](README.md) · [События MQTT](event-protocol-mqtt.md) · [Типы событий](event-types-reference.md)

---

## Назначение

Данный документ является **единым источником истины** по числовым тегам свойств событий, используемых внутри объектов массива `"300"` в MQTT-событиях устройств.

Все остальные документы ссылаются на этот справочник и **не дублируют** полные таблицы тегов.

---

## Формат массива `"300"`

Поле `"300"` является **массивом анонимных JSON-объектов**.

Каждый объект внутри `"300"` состоит из именованных элементов, где:

- **имя элемента** — числовой тег вида `3xx`, `4xx` и т.п., определённый в данном справочнике;
- **значение элемента** — допустимый JSON-тип (`number`, `string`, `boolean`, `object`, `array`, `null`), определяемый спецификацией конкретного тега.

```json
{
  "300": [
    {"304": 1, "321": 1}
  ]
}
```

> Поле `"300"` всегда является массивом, даже если содержит один объект.  
> Теги, не определённые в данном справочнике, должны игнорироваться обработчиком.

---

## Справочник тегов

> **Матрица совместимости ниже отражает документированные варианты устройств:** `Platerra`, `Siplite`, `l4-hmi`.  
> `✅` — тег задокументирован для данного варианта; `—` — совместимость не зафиксирована в текущем event-контракте.

### Теги идентификатора ввода (`301`–`303`)

| Тег | Тип | Описание | Platerra | Siplite | l4-hmi |
|-----|-----|----------|:--------:|:-------:|:------:|
| `301` | `string` | Идентификатор (код карты, пин-код, биометрия и т.п.) | — | ✅ | — |
| `302` | `int` | Тип устройства ввода: `1` — Wiegand, `4` — TouchPad, `5` — API_CODE_INPUT, `6` — NFC и т.д. | — | ✅ | — |
| `303` | `int` | Результат валидации идентификатора: `0` — не найден, `1` — привязан к ячейке, `2` — есть в БД, но не привязан, `3` — администратор | — | ✅ | — |

### Теги ячейки и контроллера (`304`–`309`)

| Тег | Тип | Описание | Platerra | Siplite | l4-hmi |
|-----|-----|----------|:--------:|:-------:|:------:|
| `304` | `int` | Логический номер ячейки / GPIO / двери (0..65535; `65535` — не привязан) | ✅ | ✅ | — |
| `305` | `int` | Идентификатор (или адрес в сети RS-485) платы подчинённого контроллера (0..255) | — | ✅ | — |
| `306` | `int` | Номер GPIO-канала контроллера (например, номер разъёма на замковой плате) (0..255) | — | ✅ | — |
| `307` | `uint32` | Битовая маска состояния GPIO-датчиков **до** события (по каналам 0–31) | — | ✅ | — |
| `308` | `uint32` | Битовая маска состояния GPIO-датчиков **после** события (по каналам 0–31) | — | ✅ | — |
| `309` | `string` | Список идентификаторов (карт/пинов), связанных с ячейкой (в виде строки, напр., JSON-массива) | — | ✅ | — |

### Теги системной информации устройства (`310`–`340`)

| Тег | Тип | Описание | Platerra | Siplite | l4-hmi |
|-----|-----|----------|:--------:|:-------:|:------:|
| `310` | `string` | Версия ПО/прошивки устройства (напр., `"1.04.025"`) | ✅ | ✅ | — |
| `311` | `int` | ⚠️ **deprecated** Положение DIP-переключателей (битовая маска 16 бит) | — | ✅ | — |
| `312` | `int` | Количество привязанных ячеек к каналам управления | — | ✅ | — |
| `313` | `int` | Свободная память устройства в байтах (`esp_get_free_heap_size()`) | — | ✅ | — |
| `314` | `string` | MAC-адрес устройства | ✅ | ✅ | — |
| `315` | `uint32` | Битовая маска текущего состояния входов (датчиков) платы | — | ✅ | — |
| `316` | `int` | Количество записей в локальной БД контроллера | — | ✅ | — |
| `317` | `int` | Количество свободных записей в локальной БД | — | ✅ | — |
| `318` | `int` | Номер страницы при постраничной передаче данных (например, БД) | — | ✅ | — |
| `319` | `int` | Признак последней страницы (`1` — последняя, `0` — продолжение) | — | ✅ | — |
| `320` | `array` | Массив объектов с данными (используется при постраничной передаче) | — | ✅ | — |
| `321` | `int` | Состояние канала/ячейки: `0` — закрыто, `1` — открыто | ✅ | ✅ | — |
| `322` | `int` | ⚠️ **deprecated** Идентификатор текущего состояния FSM (Finite State Machine) контроллера | — | ✅ | — |
| `323` | `string` | IP-адрес при подключении по Ethernet | ✅ | ✅ | — |
| `324` | `string` | Серийный номер контроллера, sn | ✅ | ✅ | — |
| `325` | `string` | IP-адрес при подключении по Wi-Fi (в текущем коде дублирует `323`) | ✅ | ✅ | — |
| `326` | `string` | ⚠️ **deprecated** ReplyId — идентификатор принятого серверного сообщения (для подтверждений) | — | ✅ | — |
| `327` | `int` | ⚠️ **deprecated** Состояние кнопок/DIP до изменения (битовая маска 16 бит) | — | ✅ | — |
| `328` | `int` | ⚠️ **deprecated** Состояние кнопок/DIP после изменения (битовая маска 16 бит) | — | ✅ | — |
| `329` | `int` | Версия аппаратной части (Hardware revision) | — | ✅ | — |
| `330` | `int32` | Уникальный числовой ID контроллера в системе | ✅ | ✅ | — |
| `331` | `int` | ⚠️ **deprecated** Тип подключённой платы расширения: `0` — цифровая, `1` — аналоговая | — | ✅ | — |
| `332` | `int` | Идентификатор активной конфигурации приложения (0..16535) | — | ✅ | — |
| `333` | `int` | Идентификатор активной UI-конфигурации (0..16535) | — | ✅ | — |
| `334` | `int` | Номер UART-порта: `0` — UART0, `1` — UART1, `2` — UART2, ... | — | ✅ | — |
| `335` | `string` | Данные с UART в кодировке Base64 | — | ✅ | — |
| `336` | `int32` | Контрольное количество отправленных событий за интервал мониторинга (обычно за 10 минут) | — | ✅ | — |
| `337` | `string` | Режим Ethernet: `"eth two ports"` (при `eth_port_mode==1`) или `"simple switch"` (в остальных режимах) | — | ✅ | — |
| `338` | `int` | Количество активных WebSocket-подключений на устройстве | — | ✅ | — |
| `339` | `string` | Возраст системного времени в секундах (строка), источник — `l4_msg_get_time_age_sec_str()` | — | ✅ | — |
| `340` | `object` | Диагностика SIP: состояние регистрации и краткие счётчики/критичные события. Формат описан в [`event-protocol-mqtt.md`](./event-protocol-mqtt.md) | — | ✅ | — |

### Теги OTA и прошивки STM32 (`341`–`352`)

| Тег | Тип | Описание | Platerra | Siplite | l4-hmi |
|-----|-----|----------|:--------:|:-------:|:------:|
| `341` | `string` | Строковый код результата: `"OTA_OK"`, `"OTA_ERR_NET"`, `"OTA_ERR_NO_SPACE"`, `"OTA_ERR_IMAGE_INVALID"`, `"OTA_ERR_INTERNAL"` (OTA) или аналог для STM32 BIN | — | ✅ | — |
| `342` | `string` | Человекочитаемое описание результата (≤ 128 символов) | — | ✅ | — |
| `343` | `string` | URL загрузки бинарного файла | — | ✅ | — |
| `344` | `uint32` | Размер загруженной прошивки (байт) | — | ✅ | — |
| `345` | `string` | SHA-256 ожидаемый (hex-строка) | — | ✅ | — |
| `346` | `string` | SHA-256 вычисленный (hex-строка) | — | ✅ | — |
| `347` | `array[string]` | Упорядоченный список имён параметров, реально включённых в отчёт (`status`, `error_stage`, `retries_tx`, `fw_time_ms`, `fw_size_bytes`) | — | ✅ | — |
| `348` | `string` | Статус результата прошивки STM32: `"ok"` или `"error"` | — | ✅ | — |
| `349` | `string` | Этап ошибки прошивки STM32; публикуется только при ошибке | — | ✅ | — |
| `350` | `uint32` | Количество TX-ретраев во время прошивки STM32; публикуется только если `!= 0` | — | ✅ | — |
| `351` | `uint32` | Общее время прошивки STM32 в миллисекундах | — | ✅ | — |
| `352` | `uint32` | Размер прошивки STM32 в байтах | — | ✅ | — |

### Теги SIP-регистрации (`353`–`359`)

| Тег | Тип | Описание | Platerra | Siplite | l4-hmi |
|-----|-----|----------|:--------:|:-------:|:------:|
| `353` | `string` | Факт изменения состояния SIP-регистрации: `"REGISTERED"` (вход) или `"LOST_REGISTERED"` (подтверждённый выход) | — | ✅ | — |
| `354` | `string` | Причина выхода из `REGISTERED`. Присутствует только при `353 = "LOST_REGISTERED"`. Значения: `"unreg"`, `"error"`, `"ip_lost"`, `"restart"` | — | ✅ | — |
| `355`–`359` | — | Зарезервированы | — | — | — |

### Теги состояния ячеек постамата (`360`–`369`)

| Тег | Тип | Описание | Platerra | Siplite | l4-hmi |
|-----|-----|----------|:--------:|:-------:|:------:|
| `360` | `array` | Список состояний ячеек постамата. Массив объектов, каждый из которых содержит теги `304` (номер ячейки) и `321` (состояние ячейки). | ✅ | ✅ | — |
| `361`–`369` | — | Зарезервированы для различных данных о ячейках (будущее использование) | — | — | — |

### Тег seed-инициализации (`370`)

| Тег | Тип | Описание | Platerra | Siplite | l4-hmi |
|-----|-----|----------|:--------:|:-------:|:------:|
| `370` | `array` | **`seed_data`** — слепок NVS-записей, установленных при seed-инициализации устройства (первый запуск / factory-reset). Каждый элемент совместим по структуре с форматом `method_code 49/50` (см. [`event-types-reference.md`](./event-types-reference.md#код-65-seedinitdone)). | — | ✅ | — |
| `371`–`398` | — | Зарезервированы | — | — | — |
| `399` | `string` | Raw payload (строка) — внутренний passthrough для событий с `msg_event_type >= 1000` | — | ✅ | — |

### Теги результата обновления UI-каталога `l4-hmi` (`401`–`410`)

| Тег | Тип | Описание | Platerra | Siplite | l4-hmi |
|-----|-----|----------|:--------:|:-------:|:------:|
| `401` | `string` | Строковый код результата / ошибки обновления UI-каталога. Пример: `"parse_error"` — каталог скачан, но JSON / валидация отклонены парсером. | — | — | ✅ |
| `402` | `int` | Версия UI-каталога, которую устройство пыталось применить. | — | — | ✅ |
| `403` | `int` | Активная версия UI-каталога до попытки обновления. | — | — | ✅ |
| `404` | `int` | Активная версия UI-каталога после попытки обновления. | — | — | ✅ |
| `405` | `string` | Активный слот UI-каталога после завершения операции (например, `"a"` или `"b"`). | — | — | ✅ |
| `406` | `string` | SHA-256 скачанного файла UI-каталога (hex-строка). | — | — | ✅ |
| `407` | `uint32` | Размер скачанного файла UI-каталога в байтах. | — | — | ✅ |
| `408` | `uint32` | Длительность операции обновления в миллисекундах. | — | — | ✅ |
| `409` | `string` | `correlation_id` исходного RPC-задания, инициировавшего обновление UI-каталога. | — | — | ✅ |
| `410` | `string` | Диагностическая причина / текст ошибки для логов и поддержки. | — | — | ✅ |

### Теги события `SIPLITE_COMMAND_ACCEPTED` (`420`–`425`)

| Тег | Тип | Описание | Platerra | Siplite | l4-hmi |
|-----|-----|----------|:--------:|:-------:|:------:|
| `420` | `string` | `command_status` — статус локальной команды; для события `73` ожидается `"ACCEPTED"`. | — | ✅ | — |
| `421` | `string` | `command_source` — источник команды в локальном контуре (например, `"client2"`). | — | ✅ | — |
| `422` | `int` | `method_code` принятой локальной команды. | — | ✅ | — |
| `423` | `string` | `local_command_id` — локальный идентификатор команды в контроллере. | — | ✅ | — |
| `424` | `boolean` | `has_corr_id` — признак наличия внешнего `correlation_id`. | — | ✅ | — |
| `425` | `string` *(optional)* | `ext_task_id` — внешний идентификатор задачи, если был передан. | — | ✅ | — |

#### Структура объекта внутри `360`

Каждый элемент массива `"360"` является анонимным объектом, структура которого регулируется данным справочником:

| Тег | Тип | Описание |
|-----|-----|----------|
| `304` | `int` | Логический номер ячейки |
| `321` | `int` | Состояние ячейки: `0` — закрыто, `1` — открыто |

---

## Примеры

### Пример 1: Открытие ячейки (`200: 13`) с полными данными контроллера

```json
{
  "101": 20338,
  "102": "2026-02-18T01:43:16+03:00",
  "200": 13,
  "300": [
    { "304": 1, "305": 1, "306": 22, "307": 35921924, "308": 8392849 }
  ]
}
```

### Пример 2: Состояние всех ячеек постамата (`200: 63`)

```json
{
  "101": 502,
  "102": "2026-04-22T13:48:02+03:00",
  "200": 63,
  "300": [
    {
      "360": [
        { "304": 1, "321": 1 },
        { "304": 2, "321": 1 },
        { "304": 3, "321": 0 }
      ]
    }
  ]
}
```

> **Интерпретация:** Устройство сообщает о текущем состоянии всех ячеек: ячейки №1 и №2 открыты (`321: 1`), ячейка №3 закрыта (`321: 0`).

---

## Диапазоны тегов

### Тег `450`: gauge IPCamera (84)

Тип `object`, producer `Siplite`. Контракт версии 1:

```json
{
  "450": {
    "schema_version": 1,
    "snapshot_id": "739a5702-409a-4b59-b48b-35f91e9ee830",
    "reason": "rpc",
    "operation_id": "5c75b4ed-2488-4769-b23a-2afae64ea22d",
    "observed_at": "2026-10-11T14:00:00Z",
    "cameras": [{
      "camera_id": "cam:ip000001",
      "status": "read_only",
      "stale": false,
      "ip": "192.168.77.2",
      "mac": null,
      "firmware": null,
      "revision": null,
      "config": {"video0": {"fps": 15, "bitrate": 1024}},
      "capabilities": {"read": true, "write": false, "fields": []},
      "telemetry": null,
      "last_operation": {"status": "unsupported", "error": "schema_unavailable"}
    }]
  }
}
```

`reason`: `discovered`, `availability_changed`, `periodic`, `rpc`.
`operation_id`: UUID RPC или null для фонового снимка. `observed_at`: UTC
последнего чтения, null если чтения не было (время публикации остаётся в 102).
`status`: `ready`, `read_only`, `unavailable`, `auth_failed`.
`config`: нормализованные управляемые параметры; null при отсутствии чтения.
`stale=true` обозначает last-known, не текущее состояние. revision может быть
null если нормализация/типизация не подтверждены; иначе SHA-256 по RPC-контракту.
`capabilities.fields`: объекты с `path`, `type`, `writable`, `disruptive` и
доступными `min`, `max`, `enum`, `unit`. Наличие schema поля не разрешает
запись за пределами approved allowlist. `telemetry` — только отдельно
измеренные значения с источником и временем наблюдения. `last_operation`
повторяет outcome соответствующего RPC, включая unsupported/unknown.

Discovery этапа 2: поле `schema_declared` сообщает, что описание approved path
извлечено и разобрано из схемы камеры. Допустимы дополнительные метаданные
`default`, `readOnly`, `multipleOf`, `x-unit`, `x-live`, `description`.
JSON Schema `minimum`/`maximum` нормализуются в `min`/`max`; `type` берётся из
описания, если объявлен. Отсутствие границы или единицы не разрешает её
угадывать. Неизвестный формат/тип схемы сохраняет read-only. Каждый descriptor
и его значения ограничиваются по размеру; пропущенные обязательные для writer
ограничения запрещают запись, а не включают permissive fallback.

Day/night discovery adds **read-only** approved configuration paths:
`nightMode.lightMonitor`, `colorToGray`, `irCut`, `backlight`, `irCutPin1`,
`irCutPin2`, `backlightPin`, `minThreshold`, `maxThreshold`, `monitorDelay`
(all prefixed by `nightMode.`). Pins and thresholds are diagnostics, not user
write controls. RPC161's existing write allowlist is unchanged. These observed
configuration fields participate in the canonical configuration revision.
Missing fields remain absent; their type/unit/support must not be guessed.

Optional `telemetry` from a bounded authenticated read of `/metrics/night` is
`{source, observed_at, status, metrics, error?}`. Status is `ok`, `unsupported`,
`auth_failed`, `unavailable`, `timed_out` or `invalid_metrics`. Only exact
unlabelled gauges `night_enabled`, `ircut_enabled`, `light_enabled`,
`night_ircut`, `night_light` with numeric0/1 values are retained under their
original names. Missing gauges are absent (not zero); duplicate/invalid known
gauges invalidate the metric sample instead of manufacturing a state.
Read-only `/metrics` fallback is permitted only when the group endpoint returns
404/405/501, with the same auth/interface/size/deadline limits. No raw metrics,
unknown samples, credentials or labels enter the snapshot. Observed software
mode/filter/lamp flags do not prove physical actuator wiring or movement.
Discovery alone advertises no day/night writer or action support.

With RPC162 implemented, optional capabilities.day_night is
`{write, modes, physical_actuators_verified:false, unavailable_reason?}`.
Software modes auto/day/night require a confirmed boolean lightMonitor schema,
usable night_enabled telemetry and an approved config writer. This is software
mode control, not proof of installed filter/lamp actuators. Missing readings
keep the control unavailable with an explicit reason; physical GPIO controls
remain excluded. last_operation may contain requested_mode and
command_http_status; RPC162's RES applied_fields reports confirmed final
nightMode.lightMonitor and/or day_night.mode changes, excluding rollback.

Firmware0017 adds optional camera.identity `{source,status,observed_at,
openipc_version?,majestic_version?}` from bounded fixed GET /cgi-bin/status.cgi.
Only a redirect/unsupported response permits fixed /cgi-bin/dashboard.cgi
fallback; auth failures do not. Extract only bounded printable Firmware/Version
and Majestic definition-list text. Never publish raw HTML, scripts or secrets.
camera.firmware may mirror a confirmed OpenIPC version; missing stays null.
Version text accepts normalized ASCII whitespace and commas from Majestic -v,
at most96 characters after normalization. Nested HTML, entities, duplicate
version labels and overlong text remain invalid; no raw status page is published.

Optional telemetry.health `{source:"/metrics",status,observed_at,metrics,
uptime_sec?,majestic_uptime_sec?}` keeps exact unlabelled finite scalar names:
node_time_seconds, node_boot_time_seconds, app_boot_time_seconds,
node_memory_MemTotal_bytes, node_memory_MemFree_bytes,
node_memory_MemAvailable_bytes, node_memory_Active_file_bytes,
node_memory_Inactive_file_bytes, node_memory_SReclaimable_bytes,
node_hwmon_temp_celsius, isp_fps, venc0_rcvd_bytes, venc0_rcvd_frames.
Counters/bytes are nonnegative and <=2^53; temperature -40..150C, FPS0..240.
Duplicate/invalid known samples invalidate this probe; unknown names and labels
are not published. Status values follow the existing bounded metrics probe.
Derive uptime only from consistent camera time/boot readings, never ESP time;
do not invent zero, available-memory sums, CPU load or measured encoder FPS.
Snapshot/probe age is calculated by consumers from observed_at; configured
FPS/bitrate and observed ISP FPS/counters remain distinct measurements.

Diagnostics extension adds snapshot `freshness_max_age_sec=330`, covering the
300s periodic poll plus jitter and bounded probe time. Consumers compute age
from snapshot/probe observed_at using their own trusted UTC clock: null or
failed probe means unknown; age>330 or camera.stale means stale; timestamp more
than5s in the future means clock_invalid. A stored gauge never remains fresh
merely because its original stale=false. This does not change gauge storage.
health.clock is `{status:"within_tolerance"|"skewed"|"unknown",
offset_sec?,tolerance_sec:300,reference:"esp_utc"}`. Offset is camera time minus
ESP UTC only when both clocks are valid; within_tolerance does not assert NTP
synchronization. Uptime continues to use camera clock differences independently.

Optional camera.power is `{source:"tca6408a_output",signal:"EN_1_12V",
state:"on"|"off"|"unknown",enabled:boolean|null,observed_at:UTC|null}`.
It describes verified P3 output configuration/latch, not measured supply voltage
or camera readiness. It is readable even with unavailable camera/network/config.
capabilities.power advertises fixed on/off/restart, restart_off_ms=3000, and
requires_idle=true. RPC164 last_operation includes requested_action; RES and
gauge contain the same output readback. Powered-off snapshots have config=null,
no fabricated identity/health, and status=unavailable with power.state=off.

capabilities.quality may contain presets with id, patch, available and
unavailable_reason, validation="schema_and_policy". Availability means the
adapter can validate the preset, not physical video verification. Report
policy_values/policy_unit separately from the camera's enum/unit/ranges.
RPC163 last_operation may contain requested_preset; status and applied_fields
follow the method contract. Event84 format and existing consumers remain v1.

Снимок до 16384 UTF-8 bytes, не более четырёх камер; config/capabilities
содержат только approved параметры, без secrets, raw YAML и полного schema.
Превышение лимита нельзя исправлять молчаливым обрезанием настроек: producer
возвращает явный `snapshot_too_large` и не объявляет успешную доставку.
Тип/схема gauge на сервере v1 сохраняются без интерпретации; producer отвечает
за shape и редактирование secrets. На сервере доступ ограничивается tenant.

| Диапазон | Назначение |
|---------|-----------|
| `301`–`303` | Данные события ввода идентификатора (`IdInput`) |
| `304`–`309` | Данные о ячейках, каналах и GPIO |
| `310`–`340` | Системные данные устройства (Hello/HealthCheck), DIP, SIP-диагностика |
| `341`–`346` | Результаты OTA и загрузки бинарника STM32 |
| `347`–`352` | Результаты прошивки STM32 |
| `353`–`354` | SIP-регистрация |
| `355`–`359` | Зарезервированы |
| `360` | Список состояний ячеек постамата |
| `361`–`369` | Зарезервированы для данных о ячейках постамата |
| `370` | `seed_data` — слепок NVS-записей seed-инициализации |
| `371`–`398` | Зарезервированы |
| `399` | Raw payload (внутренний passthrough) |
| `401`–`410` | Результат задания по обновлению UI-каталога `l4-hmi` |
| `420`–`425` | Событие `SIPLITE_COMMAND_ACCEPTED` (локальный аудит приёма/доставки команды) |
| `440`–`445` | Инвентаризация сертификата и L4 Tools, событие `75` |
| `446`–`448` | Пользовательские события `900–999` |
| `449` | Объект операции обновления L4 Tools, событие `76` |
| `450` | Объект состояния IP-камер, gauge `84` |

---

## Совместимость и расширяемость

- Вариант совместимости `l4-hmi` добавлен в матрицу как отдельный event-контракт устройства; для него задокументированы собственные теги результата обновления UI-каталога `401`–`410`.
- **Клиентам рекомендуется игнорировать неизвестные теги** — новые теги могут добавляться в диапазоны `3xx` и `4xx` без изменения версии протокола.
- Зарезервированные теги (`355`–`359`, `361`–`369`, `371`–`398`) **не должны использоваться** клиентами для хранения или обработки данных до официального назначения.
- Тег `399` является внутренним механизмом кодека для событий с `msg_event_type >= 1000` и не является частью стандартного wire-формата для новых событий.
- Один и тот же тег (например, `304`) может иметь одинаковый семантический смысл в разных событиях — это является частью дизайна протокола.

---

## 🖥️ Служебные и пользовательские события

### Событие 75 · Сертификат и инвентарь

| Тег в `300[0]` | Тип | Значение |
| :--- | :--- | :--- |
| `324` | string | SN producer; сервер использует routing SN для идентичности |
| `440` | string | Источник `l4con` |
| `441` | string | Отпечаток активного сертификата |
| `442` | string | Серийный номер сертификата |
| `443` | string | NotAfter UTC |
| `444` | array | Снимок установленных EXE |
| `445` | string / null | Версия установленного пакета, не PE-версия отдельного EXE |

Объект `444` содержит `name`, относительный `path` с `/`, `arch`, `present`, `file_version` (string/null), `size` в байтах, `modified_utc` (UTC string/null), `sha256` (hex/null). Недоступный или отсутствующий EXE имеет `present=false`.

Для `445` producer предпочитает `installed_version` успешного `install_summary.json`, затем `state.json`, иначе `null`. Время `102` относится к публикации, а не к установке файла. IoT сохраняет снимок без перевода свойств в колонки.

### События 900–999 · Пользовательские данные

| Тег в `300[0]` | Тип | Значение |
| :--- | :--- | :--- |
| `446` | string | Текст до 1024 UTF-8 байт до JSON-экранирования; вложенный JSON остаётся текстом |
| `447` | int32 | Пользовательский код, default `0`; неверный CLI-аргумент `−1`, слишком длинный `446` — `−2` с исключением `446` |
| `448` | string / UUID | Необязательная внешняя корреляция команды или операции |

При отсутствии внешнего UUID `448` не отправляется; невалидный UUID отклоняет вызов l4con. Код завершения CLI независим от `447`: сохранение подтверждается наличием события в IoT. Несколько событий могут иметь один `448`; он не заменяет UUID публикации EVT.

### Событие 76 · Объект операции обновления

| Тег в `300[0]` | Тип | Значение |
| :--- | :--- | :--- |
| `449` | object | Полный объект операции L4 Tools update |

Объект содержит `operation_id`, `kind`/`phase`/`result`, версии, `error` и timestamps, когда они доступны. Его не разбивают на дополнительные числовые теги. `operation_id` отличается от fresh MQTT Correlation Data публикации. Назначение тега эксклюзивно для события `76`; `446–448` сохраняют пользовательский смысл. [Пример event76](event-types-reference.md).

---

[Протокол событий](event-protocol-mqtt.md) · [Типы событий](event-types-reference.md) · [REST истории](2-events-api-format-description.md).

Контракты хранения и обработки сверены с `master` на 09.10.2026; device-specific значения отражают документированные контракты producer.
