# 🔢 RPC · Реестр методов

> Документированные команды устройств и специальные контракты служебных агентов. Реестр расширяется и не является автоматической проверкой возможностей прошивки.

[← Документация](README.md) · [RPC](mqtt-rpc-protocol.md) · [REST задач](1-task-workflow-doc.md)

> 📡 **Параметры команды применимы к MQTT и REST.** В REST передавайте `method_code` и `payload`; в MQTT RSP они находятся в `header.method_code` и `payload`. Примеры `res` ниже показывают содержимое результата. Transport User Properties `status_code` и `result_uid` передаются отдельно; поле статуса внутри JSON их не заменяет. REST-история нормализует результаты и маскирует чувствительные поля. [MQTT-конверт](mqtt-rpc-protocol.md) · [REST-конверт](1-task-workflow-doc.md).

> 🧩 **Матрица совместимости ниже отражает документированные варианты устройств:** `Platerra`, `Siplite`, `l4-hmi`.
> `✅` — `method_code` задокументирован для данного варианта; `—` — совместимость не зафиксирована в текущем RPC-контракте.

---

## 🧭 Что важно помнить

- `method_code` определяет действие, которое устройство должно выполнить в рамках RPC-запроса от сервера.
- Для всех RPC-сообщений обязательна сквозная передача `correlationData`.
- Для `Platerra` в текущем публичном контракте задокументирован только `method_code = 51`.
- Матрица `Platerra` / `Siplite` / `l4-hmi` ниже относится к документированным контроллерным командам. Служебные методы L4 Tools имеют отдельные контракты агента.
- Для `l4-hmi` в текущем публичном контракте задокументированы `17`, `21`, `23`.
- Если ответ `/res` не содержит специальных полей, используется стандартный ответ:

```json
{
  "status": "OK",
  "method_code": 49
}
```

---

## 🗂️ 1. Диапазоны и назначение кодов

| Диапазон / код | Тип | Назначение |
| :-- | :-- | :-- |
| `1..2999` | ⚙️ Стандартные | Обрабатываются во внутренних подсистемах прошивки: OTA, NVS, UART, загрузка и сброс данных |
| `3000..3999` | 🌐 Интерактивные | Сквозная передача запросов во внешние шлюзы через WebSocket |
| `7000..7099` | 🖥️ Служебные методы | Диагностика, renewal, файловый менеджер и сопровождение L4 Tools; поддержка зависит от агента |
| `0xFFFF` / `65535` | 🚨 Терминальный | Fail-fast код для завершения вызова при ошибке структуры или валидации |

> ⚠️ Для интерактивных `method_code` из диапазона `3000..3999` устройство обязано завершать вызов в терминальное состояние, то есть сразу публиковать `/res` со статусом `500`, даже если внешний WS-клиент недоступен.

---

## 🧾 2. Реестр `method_code`

| `method_code` | Константа | Описание | Platerra | Siplite | l4-hmi | Связанная документация |
| :-- | :-- | :-- | :--: | :--: | :--: | :-- |
| `15` | `CMD_LOAD_CELLS_FROM_CLOUD` | Загрузка конфигурации ячеек из облака | — | ✅ | — | — |
| `16` | `CMD_LOAD_CARDS_FROM_CLOUD` | Загрузка списка RFID-карт / доступов из облака | — | ✅ | — | — |
| `17` | `CMD_LOAD_CONFIG_FROM_CLOUD` | Загрузка конфигурации / удалённого ресурса в устройство. Для `l4-hmi` задокументирован кейс `UI-Catalog`. | — | ✅ | ✅ | [`mqtt-rpc-protocol.md`](./mqtt-rpc-protocol.md), [`event-types-reference.md`](./event-types-reference.md), [`event-property-tags.md`](./event-property-tags.md) |
| `18` | `CMD_SEND_485` | Отправка сырых данных или команды в шину RS-485 | — | ✅ | — | — |
| `19` | `CMD_SW_UPDATE` | OTA-обновление прошивки ESP32 | — | ✅ | — | `solution-presentation.md` |
| `20` | `CMD_SUB_REQUEST` | Выполнение суб-запросов (`batching`) | — | ✅ | — | — |
| `21` | `CMD_ESP_RESTART` | Программная перезагрузка контроллера ESP32 | — | ✅ | ✅ | [`mqtt-rpc-protocol.md`](./mqtt-rpc-protocol.md) |
| `22` | `CMD_SEND_LOG_RECORD` | Принудительная отправка логов | — | ✅ | — | — |
| `23` | `—` | Специализированный RPC-кейс. Совместимость задокументирована для `l4-hmi`; публичная детализация `payload.dt` в текущем наборе RPC-документов не закреплена. | — | ✅ | ✅ | [`mqtt-rpc-protocol.md`](./mqtt-rpc-protocol.md) |
| `26` | `CMD_ERASE_CARDS` | Очистка всех ключей / карт на устройстве | — | ✅ | — | — |
| `34` | `CMD_ERASE_LOG` | Очистка буфера лог-записей | — | ✅ | — | — |
| `35` | `CMD_API_CODE_INPUT` | Генерация программного ввода кода / доступа | — | ✅ | — | — |
| `42` | `CMD_ASCII_TO_UART` | Отправка ASCII-строки напрямую в UART | — | ✅ | — | — |
| `47` | `CMD_DELETE_CARDS` | Удаление отдельных ключей / карт доступа | — | ✅ | — | — |
| `48` | `CMD_SEND_RAW` | Отправка raw-байтов в порт | — | ✅ | — | — |
| `49` | `CMD_SET_NVS_RECORD` | Запись значений конфигурации в NVS-хранилище | — | ✅ | — | [`mqtt-rpc-protocol.md`](./mqtt-rpc-protocol.md) |
| `50` | `CMD_GET_NVS_RECORD` | Чтение значений конфигурации из NVS, возвращает массив | — | ✅ | — | [`mqtt-rpc-protocol.md`](./mqtt-rpc-protocol.md) |
| `51` | `CMD_OPERATE_CELL` | Управление ячейкой / замком / актуатором | ✅ | ✅ | — | [`mqtt-rpc-protocol.md`](./mqtt-rpc-protocol.md), [`1-task-workflow-doc.md`](./1-task-workflow-doc.md) |
| `160` | `CMD_IP_CAMERA_GET_STATE` | Прочитать OpenIPC и опубликовать gauge 84 | — | ✅ | — | Раздел «Управление IP-камерой» ниже |
| `161` | `CMD_IP_CAMERA_SET_CONFIG` | Проверить patch, применить и подтвердить чтением; gauge 84 + RES | — | ✅ | — | Раздел «Управление IP-камерой» ниже |
| `162` | `CMD_IP_CAMERA_SET_DAY_NIGHT` | Установить software Auto/Day/Night с readback; gauge84 + RES | — | ✅ | — | Только siplite ↔ OpenIPC, без STM32 |
| `163` | `CMD_IP_CAMERA_SET_QUALITY_PRESET` | Полностью проверить preset качества, применить и сверить; gauge84 + RES | — | ✅ | — | Только siplite ↔ OpenIPC |
| `164` | `CMD_IP_CAMERA_SET_POWER` | EN_1_12V on/off/restart с readback; gauge84 + RES | — | ✅ | — | ESP32 → собственный TCA6408A P3, без STM32 |
| `165` | `CMD_IP_CAMERA_DISCOVERY` | Port-2 scan/cancel; RES + gauge84 | — | ✅ | — | [Camera control](siplite-camera-control.md) |
| `166` | `CMD_IP_CAMERA_CONNECTION` | Bind и write-only credential profile; RES + gauge84 | — | ✅ | — | [Camera control](siplite-camera-control.md) |
| `167` | `CMD_IP_CAMERA_ILLUMINATION` | Verified LED/PWM и commissioning; RES + gauge84 | — | ✅ | — | [Camera control](siplite-camera-control.md) |
| `168` | `CMD_IP_CAMERA_IRCUT_SEARCH` | IR-cut inspect/search/status/cancel/apply/recover; RES + gauge84 | — | ✅ | — | [IR-cut RPC](camera-ircut-rpc.md) |
| `169` | `CMD_IP_CAMERA_IRCUT_DIAGNOSTICS` | Inspect/test existing IR-cut assignment only; RES + gauge84 | — | ✅ | — | [IR-cut RPC](camera-ircut-rpc.md) |
| `170` | `CMD_AUDIO_GET_STATE` | Audio state and capabilities; RES only | ? | ? | ? | [`Audio control`](audio-control.md) |
| `171` | `CMD_AUDIO_SET_CONFIG` | Verified independent audio configuration; RES only | ? | ? | ? | [`Audio control`](audio-control.md) |
| `172` | `CMD_AUDIO_SESSION` | Leased LAN one-way/duplex audio debugging; RES only | ? | ? | ? | [`Audio control`](audio-control.md) |
| `411` | `CMD_STM32_MCU_UPDATE` | Обновление прошивки сопроцессора STM32 | — | ✅ | — | — |
| `512` | `CMD_STM32_BIN_DOWNLOAD` | Скачивание бинарного образа для STM32 с запуском задачи | — | ✅ | — | — |
| `3000..3999` | *(интерактивные коды)* | Роутинг для локальных шлюзов / WS-клиентов | — | ✅ | — | [`mqtt-rpc-client-flow.md`](./mqtt-rpc-client-flow.md) |
| `7000` | `CMD_DIAG_STREAM_CONTROL` | Start/stop volatile output stream, включая ESP32 live logs | — | ✅ | — | [`remote-diagnostics-protocol.md`](./remote-diagnostics-protocol.md) |
| `7001` | `CMD_DIAG_EXEC` | Выполнение diagnostic command, включая поддерживаемые агентом raw-команды | — | ✅ | — | [`remote-diagnostics-protocol.md`](./remote-diagnostics-protocol.md) |
| `7002` | `CMD_DIAG_CANCEL` | Отмена активной diagnostic session | — | ✅ | — | [`remote-diagnostics-protocol.md`](./remote-diagnostics-protocol.md) |
| `65535` (`0xFFFF`) | `CMD_INVALID_JSON` | Ошибка структуры / валидации, fail-fast завершение | — | ✅ | — | [`mqtt-rpc-client-flow.md`](./mqtt-rpc-client-flow.md) |

---

## 🧩 3. Форматы `payload.dt` и ответы `res`

Новая negotiated camera-редакция `siplite-camera/1.0.0` определена в [siplite-camera-control.md](siplite-camera-control.md) и [machine package](../contracts/siplite-camera-v1/README.md). Она расширяет160..164 и вводит165..167; применяется только после capability negotiation. Ниже v1-ограничения size/isp/timeout/legacy-set описывают прежние firmware и не ограничивают новую camera-ветку. Новая ветка использует image.*, POST JSON и schema-based size, без legacy camera firmware.

### Управление питанием камеры: `164`

Согласованная транзакция: **RES + обязательный коррелированный gauge84/tag450**.
Исполнение только в siplite: ESP32 управляет существующим выходом EN_1_12V
(TCA6408A P3, active HIGH); STM32/sip_periph не участвует. Это питание камеры,
не ИК-подсветка. Другие биты экспандера не изменяются.

```json
{"dt":[{"camera_id":"cam:ip000001","action":"restart","expected_power_on":true,"allow_disruptive":true,"dry_run":false,"timeout_ms":10000}]}
```

action строго on/off/restart; expected_power_on — обязательный boolean,
сравнивается с текущим аппаратным readback под эксклюзивным relay guard.
Ревизия OpenIPC не требуется: питание должно включаться и при недоступной камере.
Только фиксированный P3, без произвольных pin/mask/url/delay. timeout1000..15000ms.
Активный relay →409 busy без изменения выхода; несовпадение состояния →409
power_state_conflict; отсутствие allow_disruptive для изменения →409
disruptive_consent_required. dry_run валидирует без переключения.
restart требует исходное питание on и не менее4000ms остатка deadline до начала;
фиксированный интервал off3000ms, после выключения включение выполняется даже
при наступившем shutdown/deadline. Ошибки readback/включения явные
power_read_failed/power_verify_failed/power_restore_failed, outcome_unknown
при неоднозначной записи, без слепого повторения restart.
on/off с уже требуемым состоянием →200 unchanged. Повтор той же correlation
возвращает сохранённый result_uid и не повторяет цикл в пределах RAM cache;
между перезагрузками дедупликация не обещается.

RES содержит requested_action, power, applied_fields ["power.enabled"] только
для подтверждённого изменения и ["power.restart"] для подтверждённого цикла.
Успех подтверждает направление/защёлку P3, а не напряжение12V, загрузку камеры
или изображение. После on/restart камера может ещё загружаться; readiness
проверяется отдельным RPC160/gauge84. Начальное поведение bootstrap остаётся on.

### Управление IP-камерой: `160` / `161`

#### Quality preset extension (firmware0017)

RPC163 is a siplite ↔ OpenIPC transaction completed by **RES plus mandatory
correlated gauge84/tag450**, with no STM32/sip_periph involvement:
`{"dt":[{"expected_revision":"<64 lowercase hex>","preset":"medium|hd",
"allow_disruptive":true,"dry_run":false,"timeout_ms":15000}]}`.
Only camera_id, timeout_ms, expected_revision, preset and strict boolean flags
are accepted. Default timeout15000ms, range1000..15000; other camera defaults
and revision rules are unchanged. Presets are product policy, not a claim
that every camera sensor/SDK supports the resolutions:

| preset | video0.size (string) | fps | bitrate (Majestic kbit/s profile) | rcMode | gopSize (string, seconds) |
|---|---|---|---|---|---|
| medium | 640x360 | 10 | 768 | vbr | "1.0" |
| hd | 1280x720 | 15 | 1024 | vbr | "1.0" |

RPC161 may write size only as these two explicit strings and gopSize as
"0.5", "1.0" or "2.0". Their Majestic string descriptors must be supported;
declared enum/readOnly/constraints remain binding. Policy values/unit are
reported separately from camera-declared limits. No arbitrary resolution,
codec, destination, numeric-to-string coercion or guessed hardware range.

163 compares live revision and validates **every** preset field before any
mutation. The existing RTP guard covers the whole sequence; active/stopping
video is busy. Dry-run/no-op never reports applied_fields. Post-json uses one
patch; legacy-set performs sequential single-field writes with fresh revisions
and readback, under the same guard. It is not atomic: stop at the first failure,
never blindly retry, and report partial_apply/outcome_unknown with the current
snapshot when appropriate. No automatic rollback over ambiguous state.
RES/last_operation may include requested_preset. applied_fields lists only
confirmed FINAL differences from the pre-operation baseline, not equal values.
Config readback verifies settings; it does not prove video delivery. Hardware
acceptance uses the operator's explicit stream confirmation for each preset.

Identity/health and snapshot freshness are defined under gauge84/tag450.
Physical IR filter acceptance is an operator observation of sound/image during
coordinated RPC162 transitions. IR illumination is outside this release scope.

Контракт v1, producer — siplite, исполнитель — OpenIPC/Majestic по внутреннему
Ethernet. STM32/sip_periph не участвует. Это локальные RPC из диапазона
`1..2999`, без зависимости от WebSocket и без изменения video ctl/lease.
Наличие метода в реестре не означает поддержку установленной прошивкой.

`160` принимает ровно один объект в `payload.dt`:

```json
{"dt":[{"camera_id":"cam:ip000001","timeout_ms":5000}]}
```

Оба поля имеют показанные defaults. `camera_id` соответствует `cam:ip` + шесть
цифр; `timeout_ms` — целое `1000..15000`, общий бюджет операции, включая очередь
и HTTP. Deadline ограничивается оставшимся TTL задачи; часы ожидания не
продлеваются при retry. Неизвестные поля запрещены.

RPC160 day/night discovery may additionally return the read-only `nightMode`
configuration and bounded current-state telemetry documented under gauge84/tag450.
The request envelope and RPC161 write allowlist remain unchanged. Desired auto
monitoring, observed software night state and physical filter/lamp support are
separate readings; discovery does not imply availability of action endpoints.

`161` добавляет обязательные `expected_revision` (64 lowercase hex SHA-256) и
`patch`, необязательные boolean `allow_disruptive=false`, `dry_run=false`:

```json
{"dt":[{"camera_id":"cam:ip000001","timeout_ms":5000,
  "expected_revision":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "patch":{"video0":{"fps":15,"bitrate":1024}},
  "allow_disruptive":false,"dry_run":false}]}
```

Допустимые пути v1: `video0.fps`, `video0.bitrate`, `video0.gopSize`,
`video0.rcMode`, `video0.size`, `isp.mirror`, `isp.flip`, `isp.rotate`,
`isp.luminance`, `isp.contrast`, `isp.saturation`, `isp.hue`.
Patch содержит 1..12 scalar значений; null, вложенные объекты/массивы, NaN/Inf,
пустые секции запрещены. Строка до 64 символов, весь исходный payload до
4096 UTF-8 bytes. Значения и единицы определяет схема конкретной камеры.
Сервер проверяет envelope/allowlist, устройство повторяет эти проверки и
проверяет типы/ranges/enums по обнаруженным capabilities. Разрешённый путь
не является обещанием поддержки камерой.

Day/night extension: RPC161 additionally permits `nightMode.lightMonitor`
(strict boolean); the installed schema must confirm its boolean writer.
Pins, thresholds, colorToGray and actuator modes remain read-only.

RPC162 is a high-level **siplite ↔ OpenIPC** transaction, no sip_periph/STM32:
`{"dt":[{"expected_revision":"<64 lowercase hex>","mode":"auto|day|night",
"allow_disruptive":true,"dry_run":false,"timeout_ms":15000}]}`.
camera_id/timeout defaults and bounds are the same as160; revision/mode are
required; only these fields and strict boolean consent/dry-run are permitted.
Every result must correlate with event84/tag450, including unsupported/failure.

Auto sets and verifies lightMonitor=true. Day/night disables the auto monitor
with the selected explicit config writer, then invokes **one** fixed
GET /night/off or /night/on and verifies the exact night_enabled gauge. Config
and software state are separate readbacks. Revision/prevalidation/consent and
the existing exclusive RTP guard cover the complete transaction. No toggles,
arbitrary URLs, GPIO writes or new camera power/I2C operations are allowed.
Already matching monitor/software state returns unchanged; dry-run returns
validated, with no mutation/applied_fields. Active/stopping video returns busy.

Missing schema or usable night_enabled telemetry yields explicit unsupported
before mutation. A command404/405/501 is unsupported, never success. If this
definite rejection followed disabling auto, restore the original monitor using
a fresh revision and verify it; failure to reconcile returns partial_apply or
outcome_unknown with the latest snapshot. Ambiguous commands are never blindly
replayed. Successful mutation requires verified monitor and software mode;
unavailable readback is outcome_unknown, mismatch is verify_failed/partial_apply.
RES/last_operation may include requested_mode and command_http_status.
applied_fields uses nightMode.lightMonitor and day_night.mode for confirmed
final changes; rolled-back monitor changes are excluded. Physical filter/lamp
motion is unverified even when software flags change. Capability advertisement
distinguishes software modes from verified physical actuators.

Первый writer-профиль siplite (quality-controls) включает только
`video0.fps`, `video0.bitrate`, `video0.rcMode`, когда установленные schema
descriptors подтверждают integer/integer/string+enum и не содержат readOnly
или неподдерживаемых validation keywords. Неподдерживаемые поля (включая
size/GOP без достаточной типизации) отклоняют весь patch до POST.
Отдельные локальные ограничения транспорта/продукта: FPS1..30, bitrate128..2048
(в шкале camera API; профиль Majestic использует kbit/s). Это **не** обнаруженные
аппаратные пределы камеры; в gauge они передаются как `policy_min/policy_max`,
отдельно от schema `min/max`. Ограничения схемы дополнительно обязательны.
Любая фактическая запись требует allow_disruptive=true и отсутствия активного
или ещё не завершившегося RTP relay. Общий lifecycle guard исключает гонку со
stream_start. Несогласованное изменение возвращает409 busy без записи.
Revision вычисляется по всем approved config полям, а не только writable subset.
Совпадающий patch возвращает200 unchanged без POST; dry_run возвращает200
validated без applied_fields. POST при неоднозначном ответе не повторяется:
один GET readback устанавливает ok/partial_apply/verify_failed/outcome_unknown.

Совместимость writer выбирается явно через siplite cfg_cam/writer:
`post-json` (default, POST /api/v1/config) или `legacy-set`
(один GET /api/v1/set?<approved.path>=<validated.value>). Это **не** автоматический
fallback после неудачного POST: каждый RPC использует только выбранный endpoint,
с теми же revision, validation, lifecycle guard и обязательным readback/gauge.
Legacy-профиль допускает ровно одно изменяемое поле; multi-field patch получает
501 batch_unsupported до записи. Gauge capabilities содержит writer_profile и
max_patch_fields; неизвестный профиль блокирует запись. RES/last_operation могут
содержать camera_http_status, без сырых ответов/секретов камеры.

Сначала GET конфигурации и схемы, сравнение revision, проверка **всех** полей,
только затем минимальный POST patch. Неподдерживаемое поле отклоняет весь
patch до первого write: никаких silently skipped полей и best-effort успехов.
Если схема недоступна или семантика writer не подтверждена, камера read-only;
устройство не угадывает команды, не переписывает YAML и не запускает shell.
HTTP 404/405/501 или явный отказ камеры превращается в `unsupported`, а не
в crash, бесконечный retry, timeout или успешный ACK. HTTP 401/403 — отдельный
`auth_failed`. Если ответ writer неоднозначен, выполняется GET reconciliation,
повторный POST вслепую запрещён.

Изменения `video0.*` консервативно считаются disruptive и требуют
`allow_disruptive=true`; исключение допустимо лишь для проверенной capability
конкретной сборки. Во время активной трансляции encoder reload должен быть
согласован с video owner; если корректный переход не реализован, возвращается
`busy`, а не выполняется скрытое прерывание. Кодек, RTP destination, сетевые
настройки, credentials и питание вне allowlist v1. `dry_run` выполняет все
проверки и возвращает diff, без записи и без заявления «применено».

После записи обязателен GET readback и сравнение всех запрошенных полей.
HTTP 200 не является подтверждением применения; атомарность writer не
предполагается. Несовпадение возвращает `verify_failed` / `partial_apply`;
снимок отражает фактическое состояние, откат не обещается. При недоступном
readback результат `outcome_unknown`, с unknown полями и stale предыдущим
снимком, без ложного успеха.

Для **каждой принятой устройством операции** `160/161`, включая unsupported,
dry-run и ошибки камеры, producer готовит gauge 84 (тег 450), ставит его в
ограниченную очередь QoS1, затем отправляет RES с тем же `snapshot_id`.
Недоступное состояние обозначается явно: `config=null` либо last-known с
`stale=true` и временем исходного чтения. Ошибка enqueue не маскируется:
`snapshot_publish_failed`, сохранённый outcome применения остаётся в RES.
Ошибка серверной валидации POST не создаёт задачу, поэтому gauge не ожидается.

RES содержит `status`, `camera_id`, `snapshot_id`, `revision` (null при unknown),
`applied_fields`, `field_errors` (path, reason), `event_delivery="queued"` либо
`"not_queued"`; на ошибке дополнительно `error` и безопасный detail.

| Transport `status_code` | `status` / `error` | Семантика |
| :--- | :--- | :--- |
| 200 | `ok`, `validated`, `unchanged` | readback подтверждён; validated — только dry-run |
| 400 | `invalid_request` | Не прошла локальная проверка envelope/значений |
| 409 | `revision_conflict`, `busy` | Конфликт состояния; записи не было |
| 501 | `unsupported` | Ожидаемый терминальный отказ по capability, без аварии |
| 502 | `camera_unavailable`, `auth_failed`, `verify_failed`, `partial_apply`, `outcome_unknown` | Причины различаются в JSON |
| 503 | `queue_full`, `snapshot_publish_failed` | Исчерпан локальный ресурс/доставка; outcome записи указан отдельно |
| 504 | `deadline_exceeded` | Deadline до записи; после возможной записи — `outcome_unknown` |

Сервер сохраняет отрицательный RES и закрывает задачу обычным DONE: клиент
проверяет transport status и JSON, а не только task status. Correlation Data —
UUID задачи; result_uid стабилен при повторе. Gauge transport correlation
идентифицирует публикацию; `operation_id` внутри 450 связывает с RPC.
MQTT очередь/PUBACK и CMT результата не подтверждают запись gauge в БД:
потребитель сверяет `snapshot_id` через `GET /api/v1/gauges/?device_id=4619&type=84`.

Ревизия — SHA-256 канонического JSON управляемого config (отсортированные ключи,
UTF-8 без пробелов, scalar по схеме; без telemetry, capabilities и secrets).
Снимок включает config, по которому рассчитана revision. Повтор UUID задачи
в текущем boot возвращает прежний логический результат, без второго write;
кэш минимум 16 записей, вытеснение только завершённых. После reboot/вытеснения
сначала reconciliation: если patch уже совпадает, `unchanged`; иначе обязательна
проверка expected_revision. Неизвестный результат не повторяется вслепую.

### 🔹 `15` — `CMD_LOAD_CELLS_FROM_CLOUD`
- **Совместимость:** `Siplite`
- **Запрос `dt`:** формат зависит от логики парсинга ячеек; ожидается массив объектов со свойствами ячеек.

### 🔹 `16` — `CMD_LOAD_CARDS_FROM_CLOUD`
- **Совместимость:** `Siplite`
- **Запрос `dt`:** ожидаются объекты привязок карт:

```json
[
  {
    "cd": "номер_карты",
    "cl": 1
  }
]
```

### 🔹 `17` — `CMD_LOAD_CONFIG_FROM_CLOUD`

| Поле | Значение |
| :-- | :-- |
| Основной кейс в публичной документации | `UI-Catalog` |
| Совместимость кейса | `l4-hmi` |
| Что передаётся | Ссылка на удалённый UI-каталог / конфигурационный ресурс |
| Как отслеживать итог | по RPC-результату и, при необходимости, по событию `event_type_code = 70` (`L4HmiEvent`) |

- **Запрос `dt`:**

```json
[
  {
    "scope": "catalog",
    "url": "https://example.com/ui/catalog.json"
  }
]
```

- **Назначение:** инициирует загрузку и применение удалённого UI-каталога на устройстве `l4-hmi`.
- **Примечание:** поле `scope` позволяет явно указать сценарий `UI-Catalog`.
- **Связанные события:** детализированный итог операции может публиковаться отдельным событием `event_type_code = 70` с тегами `401`–`410` — см. [`event-property-tags.md`](./event-property-tags.md) и [`event-types-reference.md`](./event-types-reference.md).

### 🔹 `18` — `CMD_SEND_485`
- **Совместимость:** `Siplite`
- **Запрос `dt`:**

```json
[
  {
    "uartNum": 2,
    "txBase64": "base64_string"
  }
]
```

- **Назначение:** отправка бинарных данных в указанный UART / RS-485.

### 🔹 `19` — `CMD_SW_UPDATE`
- **Совместимость:** `Siplite`
- **Запрос `dt`:**

```json
[
  {
    "url": "https://..."
  }
]
```

- **Назначение:** запуск OTA-обновления ESP32.
- **Ошибки `res`:** `400` — невалидный URL или пустой объект, `409` — OTA уже выполняется, `500` — внутренняя ошибка.

### 🔹 `20` — `CMD_SUB_REQUEST`
- **Совместимость:** `Siplite`
- **Запрос `dt`:**

```json
[
  {
    "mt": 0
  }
]
```

- **Назначение:** пакетные команды / sub-events. Генерирует исходящие события `evt` со статусом `206` во внутреннюю шину.
- **Поддерживаемые события:** `0` (`HELLO_FROM_DEV`), `4` (`COPY_DATA_CELLS_TO_CLOUD`), `5`, `25` (`SEARCH_CARDS_BY_CELL`, с полем `"cl"`), `28`, `37`.

### 🔹 `21` — `CMD_ESP_RESTART`
- **Совместимость:** `Siplite`, `l4-hmi`
- **Запрос `dt`:** может быть пустым, значение игнорируется.
- **Назначение:** мгновенный вызов `esp_restart()`.

### 🔹 `23` — специализированный RPC-кейс
- **Совместимость:** `Siplite`, `l4-hmi`
- **Статус:** код внесён в матрицу совместимости, однако публичная детализация `payload.dt` и структуры `res` пока не зафиксирована в текущем наборе RPC-документов.

### 🔹 `35` — `CMD_API_CODE_INPUT`
- **Совместимость:** `Siplite`
- **Запрос `dt`:** массив ASCII-строк длиной не более `15` символов.

```json
[
  "12345",
  "67890"
]
```

- **Назначение:** генерация программных событий чтения карт / кодов.
- **Ответ `res`:** для каждой строки формируется индивидуальный результат со `status_code`: `200` (`accepted`), `423` (`dropped_invalid` или `dropped_busy`).

### 🔹 `42` — `CMD_ASCII_TO_UART`
- **Совместимость:** `Siplite`
- **Запрос `dt`:** публикует переданные в поле `"tx"` строки напрямую на внешний интерфейс.
- **Примечание:** ожидается расширение стандарта вида `"tx": "строка"`.

### 🔹 `48` — `CMD_SEND_RAW`
- **Совместимость:** `Siplite`
- **Запрос `dt`:**

```json
[
  {
    "type": "udp",
    "port": 62778,
    "txBase64": "base64_string"
  }
]
```

### 🔹 `49` — `CMD_SET_NVS_RECORD`
- **Совместимость:** `Siplite`
- **Запрос `dt`:**

```json
[
  {
    "p": "cfg",
    "ns": "cfg_eth",
    "k": "eth_port_mode",
    "t": "i32",
    "v": 0
  }
]
```

- **Примечание:** подробности и типы (`str`, `i32` и др.) описаны в [`mqtt-rpc-protocol.md`](./mqtt-rpc-protocol.md).
- **Ответ `res`:**

```json
{
  "status": "OK",
  "method_code": 49,
  "records_updated": 1
}
```

### 🔹 `50` — `CMD_GET_NVS_RECORD`
- **Совместимость:** `Siplite`
- **Запрос `dt`:**

```json
[
  {
    "ns": "cfg_eth"
  }
]
```

- **Ответ `res`:** возвращает сырой массив записей:

```json
[
  {
    "k": "...",
    "t": "...",
    "v": "..."
  }
]
```

### 🔹 `51` — `CMD_OPERATE_CELL`
- **Совместимость:** `Platerra`, `Siplite`
- **Назначение:** управление ячейкой / замком / актуатором (однократный адресный сигнал в стек аппаратного контроллера, который осуществляет физическое исполнение команды).
- **Запрос от сервера:** должен включать параметр `cl` в массиве `dt`.

```json
[
  {
    "cl": 1
  }
]
```

- **Ожидаемый ответ `/res`:** должен явно подтверждать обработку конкретной ячейки.

```json
{
  "cl": 1,
  "ts": "2026-04-20T13:17:30.798282+00:00",
  "result": "ok",
  "accepted": true,
  "method_code": 51
}
```

### 🔹 `411` — `CMD_STM32_MCU_UPDATE`
- **Совместимость:** `Siplite`
- **Назначение:** запуск обновления прошивки сопроцессора STM32 по шине из локальной базы.

### 🔹 `512` — `CMD_STM32_BIN_DOWNLOAD`
- **Совместимость:** `Siplite`
- **Запрос `dt`:**

```json
[
  {
    "url": "https://...",
    "sha256": "64_hex_chars_hash",
    "chunk_size": 1024
  }
]
```

- **Ответ `res`:** при успешном старте:

```json
{
  "status": "OK",
  "method_code": 512,
  "detail": "download task started"
}
```

- **Ошибки `res`:** `400` — плохие аргументы, `409` — загрузка уже выполняется.

### 🔸 `3000..3999` — интерактивные коды
- **Совместимость:** `Siplite`
- **Назначение:** сквозные вызовы, где `payload` и структура определяются подключённым клиентом.
- **Особенность:** fail-fast при недоступности WS-канала.

### 🔸 `7000–7002` — Remote Diagnostics / Output Streams
- **Совместимость:** агенты/прошивки с поддержкой [`remote-diagnostics-protocol.md`](./remote-diagnostics-protocol.md).
- **Транспорт управления:** только существующий RPC lifecycle (`srv/<SN>/tsk`, `dev/<SN>/req`, `srv/<SN>/rsp`, `dev/<SN>/res`).
- **Потоковый вывод:** публикуется устройством в `dev/<SN>/out`; не является event и не заменяет финальный `/res`.
- **Команды:** backend поддерживает predefined `command_id` и raw aliases. Текущий console-контракт допускает `command_line` и `shell`; разрешение конкретного действия определяет агент.

#### `7000` — `CMD_DIAG_STREAM_CONTROL`

Start ESP32 live logs / volatile output stream:

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

Stop stream:

```json
[
  {
    "action": "stop",
    "session_id": "8baf0d49-3e35-4210-87a8-111111111111",
    "stream": "esp32-log"
  }
]
```

#### `7001` — `CMD_DIAG_EXEC`

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

Финальный `/res` содержит только метаинформацию (`status`, `method_code`, `session_id`, `command_id`, `exit_code`, `output_topic`, `truncated`, `error`), а не большой stdout/stderr.

#### `7002` — `CMD_DIAG_CANCEL`

```json
[
  {
    "session_id": "8baf0d49-3e35-4210-87a8-111111111111",
    "reason": "browser_closed"
  }
]
```

---

## ✅ 4. Краткие правила для интеграции

- Перед публикацией задачи проверяйте совместимость `method_code` с вариантом устройства по матрице выше.
- Всегда передавайте `correlationData` сквозным образом.
- Для `3000..3999` обрабатывайте недоступность WS-клиента через fail-fast.
- `CMD_INVALID_JSON` (`65535` / `0xFFFF`) — документированный firmware marker ошибки. REST TaskCreate его не принимает (`method_code < 65535`), адресный Trigger ограничен `7099`. Ошибку исполнения передавайте результатом с корректным transport `status_code`.
- Если команда не требует специального JSON-ответа, возвращайте стандартный `res` с `status` и `method_code`, добавляя transport `status_code` и стабильный `result_uid`.
- Для кейса `l4-hmi` + `method_code = 17` дополнительно планируйте обработку асинхронного события `event_type_code = 70`, если бизнес-сценарию нужен детализированный итог обновления UI-каталога.

---

## 📚 5. Связанные документы по RPC

| Файл | Назначение |
| :-- | :-- |
| [`mqtt-rpc-protocol.md`](./mqtt-rpc-protocol.md) | Детальное описание транспортного протокола MQTT RPC v5: конверты, топики, User Properties, `correlationData`, polling и trigger |
| [`remote-diagnostics-protocol.md`](./remote-diagnostics-protocol.md) | Remote diagnostics и live output: `dev/<SN>/out`, output envelope, коды `7000..7002` |
| [`mqtt-rpc-client-flow.md`](./mqtt-rpc-client-flow.md) | Sequence- и flow-диаграммы RPC-обмена |
| [`mqtt-rpc-correlation-matrix.md`](./mqtt-rpc-correlation-matrix.md) | Сводка по передаче `correlationData` в каждом типе RPC-сообщений |
| [`1-task-workflow-doc.md`](./1-task-workflow-doc.md) | REST workflow задач и HTTP-форматы поверх того же `method_code` / `payload.dt` |
| [`correlation-data-guide.md`](./correlation-data-guide.md) | Руководство по передаче `correlationData` / `correlation_id` во всех клиентах и транспортах |
| [`event-types-reference.md`](./event-types-reference.md) | Реестр типов событий, включая `event_type_code = 70` для `l4-hmi` |
| [`event-property-tags.md`](./event-property-tags.md) | Реестр тегов событий, включая `401`–`410` для результата обновления UI-каталога |

## 🖥️ Служебные методы L4 Tools

| Код | Назначение | Контракт / ограничение |
| :--- | :--- | :--- |
| `7003` | Ping | Ровно `{"dt":[]}`, consumer отвечает pong |
| `7004/7005` | Пустые служебные вызовы | API принимает `{"dt":[]}`; native l4con возвращает unsupported, а не ложный keepalive ACK |
| `7010` | Legacy | Существующий контракт не переопределяется валидатором renewal |
| `7011` | Authenticated certificate renewal | Один объект PIN; правила ниже |
| `7021` | L4FM transfer | `session_id`, `action=transfer`, `operation_id`, `expires_at`, `ttl_sec` |
| `7023` | L4FM start/renew | `session_id`, `action`, `expires_at`, `ttl_sec`, без `operation_id` |
| `7020/7022` | Retired FM v1 | Отклоняются текущим FM; list/stop идут через `fmc/fmr` |
| `7030–7033` | Методы контура обновлений L4 Tools | Допущены в capability polling IoT; payload и поддержка задаются consumer-контрактом |

Это дополнение не расширяет матрицу совместимости контроллеров автоматически. Валидаторы API не заменяют проверку поддержки методом конкретного агента.

### 🔐 `7011` · Обновление сертификата

Полный task payload содержит ровно один объект:

```json
{
  "dt": [
    {"pin":"000000","pin_expires_at":4102444800,"ttl_sec":120}
  ]
}
```

PIN в примере условный. Реальный `pin` — шесть ASCII-цифр; `pin_expires_at` — UTC epoch seconds из срока PIN, выданного PB. Неизвестные поля запрещены. TTL задачи положителен и не превышает остаток срока PIN; сервер также ограничивает deadline этим сроком.

7011 всегда ждёт RSP. Только согласованный renew flow PB с проверенным действующим сертификатом использует PIN. Выдача сертификата не доказывает его установку: для сверки используются свежие наблюдения mTLS и инвентаризация event75. RES и события не должны содержать PIN.

REST-история и результат рекурсивно маскируются. Исходный PIN остаётся в delivery payload до очистки при результате, удалении или expiration. [Схема renewal](../app-service/core/schemas/certificate_renewal.py).

### 📂 L4FM v2

Старт/продление и transfer используют существующий RPC lifecycle. Navigation и подтверждённый stop вынесены в `srv/<SN>/fmc` → `dev/<SN>/fmr`; файлы передаются через S3. Общая lease монопольна с console/stream/input/view, включая того же владельца. [Полный контракт файлового менеджера](file-manager-v2.md).

### 🔄 Capability polling

Служебный consumer передаёт непустое подмножество `7001,7002,7003,7011,7021,7023,7030,7031,7032,7033` в `rpc_methods`. Отсутствующий или невалидный header оставляет legacy-ограничения. [Алгоритм выбора](mqtt-rpc-protocol.md).

Сверено с валидаторами и выборкой IoT в `master` на 09.10.2026. Поддержка и смысл device-specific команд определяются контрактом прошивки/агента.
