

# Архитектура прикладного протокола на базе MQTT v5 в концепции RPC

> **Файл:** `docs/mqtt-rpc-protocol.md`  
> **Версия:** 1.2  
> **Дата:** 2026  
> **Автор:** Oleg_
> **См. также:** [`method-codes-reference.md`](./method-codes-reference.md), [`mqtt-rpc-client-flow.md`](./mqtt-rpc-client-flow.md), [`correlation-data-guide.md`](./correlation-data-guide.md), [`remote-diagnostics-protocol.md`](./remote-diagnostics-protocol.md)

---

## 📋 Общее описание

Данный документ описывает архитектуру прикладного протокола, реализованного поверх **MQTT версии 5**, с использованием расширенных возможностей протокола (User Properties, Correlation Data) для организации **асинхронного RPC-взаимодействия** между устройством (клиент) и облачным сервером (брокер + backend).

Протокол поддерживает:
- Двунаправленный вызов процедур (RPC)
- Сквозную корреляцию через `correlationData`
- TTL
- Приоритезацию
- Поллинг и триггерные механизмы инициации запросов

> 🧩 **Совместимость `method_code` и форматы `payload.dt`** вынесены в [`method-codes-reference.md`](./method-codes-reference.md).
> Кратко: `Platerra` — только `51`, `Siplite` — все документированные коды, `l4-hmi` — `17`, `21`, `23`.

---

## 👥 Участники

| Роль | Описание |
|------|--------|
| **Устройство (Device)** | Клиент (paho, MQTTnet, ...), подключается к MQTT-брокеру по TLS. Может инициировать RPC, обрабатывать команды и отправлять результаты. |
| **Сервер (Cloud Core)** | Центральный сервер, выступающий как источник команд и получатель событий. Управляет жизненным циклом задач. |
| **MQTT Брокер** | Транспортный уровень, маршрутизирует сообщения между участниками. |


---

## 📡 Структура топиков RPC

Топики разделены по направлению и типу сообщений:

| Направление | Инициатор | Назначение |
|-----------|:---------:|---------------|
| `dev/<SN>/req` | 🔼 Device | Запрос от устройства к серверу (инициация RPC от клиента) |
| `dev/<SN>/ack` | 🔼 Device | Подтверждение получения команды от устройства (опционально) |
| `dev/<SN>/res` | 🔼 Device | Ответ устройства на задачу (результат выполнения) |
| `dev/<SN>/out` | 🔼 Device | Volatile потоковый вывод для live logs / diagnostics; не является RPC result |
| `srv/<SN>/tsk` | 🔽 Server | Анонс задачи сервером (только Trigger-сценарий) |
| `srv/<SN>/rsp` | 🔽 Server | Передача параметров задачи на устройство |
| `srv/<SN>/cmt` | 🔽 Server | Подтверждение получения результата со стороны сервера (commit) |

> `<SN>` — серийный номер устройства (уникальный идентификатор).
> `dev/<SN>/out` используется только для streaming output и не участвует в `tsk` → `req` → `rsp` → `res` → `cmt` lifecycle. Управление remote diagnostics выполняется через обычные RPC-задачи с `method_code = 7000..7002`.

---

## ⚙️ Механизм RPC (Remote Procedure Call)

### Общая последовательность

Протокол использует **асинхронную модель RPC** с **сквозным `correlation_data`**, который идентифицирует весь процесс взаимодействия.

#### Вариант 1: Инициация через поллинг (Polling)

Устройство периодически отправляет `req` с `correlationData: <UUID(0)>`, запрашивая наличие новой задачи:

```text
1. Устройство → Сервер (req):
   topic: dev/a3b1234567c10221d290825/req
   correlationData: 00000000-... (нулевой UUID)
   

2. Сервер → Устройство (rsp):
   - Если есть задача: публикует в `srv/a3b1234567c10221d290825/rsp`
   - correlationData = UUID4 назначен сервером и идентифицирует задачу
```

Стратегия выбора задачи при поллинге:

- участвуют только задачи устройства с `status < DONE`
- задача с `ttl = 0` **не участвует в выборе** (поллинг её не вернёт)
- сначала выбирается задача с максимальным `priority`
- при одинаковом `priority` выбирается задача с минимальным положительным `ttl`
- при равных `priority` и `ttl` выбирается более ранняя задача по `created_at`

> 📖 Детали TTL, правила декремента и поведение при `ttl=0` — см. [`TTL.md`](./TTL.md).

> 💡 Задача с `ttl=0` может быть доставлена только через **Trigger**-сценарий (сервер явно шлёт `tsk` с конкретным UUID). Поллинг (`req` с нулевым UUID) такую задачу **никогда не вернёт**. Применение: срочные / моментальные команды, для которых важнее доставить `tsk` + получить `ack`, чем ожидать полного цикла `rsp` → `res`.

Внутреннее окно для адресного `req` у `ttl=0` ограничено одной минутой с создания задачи. Внешнее поле `ttl` при этом остаётся равным `0`.

#### Вариант 2: Инициация сервером (Trigger)

Сервер сам инициирует взаимодействие:

```text
1. Сервер → Устройство (tsk):
   topic: srv/a3b1234567c10221d290825/tsk
   correlationData: a1b2c3d4-...
   userProperty: method_code=3001

2. Устройство → Сервер (req):
   topic: dev/a3b1234567c10221d290825/req
   correlationData: a1b2c3d4-...   
   (автоматически после получения tsk)
```


---

### 🔄 Жизненный цикл задачи

```text
[Optional] 
    ↓
  TSK  ← Сервер анонсирует задачу (только в кейсе Trigger)
    ↓
  REQ  ← Устройство запрашивает данные (оба кейса: Polling, Trigger)
    ↓
  RSP  ← Сервер отправляет тело задачи с параметрами
    ↓
  RES  ← Устройство отправляет результат
    ↓
  CMT  ← Сервер подтверждает получение результата
```

#### Подробности по этапам

| Этап | Топик | Назначение | Описание |
|------|-------|------------|----------------|
| `tsk` | `srv/<SN>/tsk` | Анонс задачи, содержит `method_code` | Только в кейсе Trigger |
| `req` | `dev/<SN>/req` | Запрос параметров задачи | ✅ Обязательно |
| `rsp` | `srv/<SN>/rsp` | Передача полезной нагрузки (JSON) | ✅ Обязательно |
| `res` | `dev/<SN>/res` | Ответ устройства (результат выполнения) | ✅ Обязательно |
| `cmt` | `srv/<SN>/cmt` | Подтверждение получения результата | ✅ Обязательно |

---

### 🔑 Correlation Data — сквозной идентификатор
> Использование `Correlation data` основано на спецификации MQTT v5, в которой это свойство выделено как обособленное.
> [Doc->MQTT v5 Correlation Data](https://docs.oasis-open.org/mqtt/mqtt/v5.0/os/mqtt-v5.0-os.html#_Toc3901067) 
> Однако, не все реализации поддерживают его корректно.
> 
> Поэтому, в ряде реализаций это свойство должно быть перенесено в общий список User Property и 
> иметь название в camelCase `correlationData`.
> Также, нужно обратить внимание, что по спецификации MQTT v5 `correlation Data` имеет тип `Binary Data`, 
> а `User Property` (ключ:значение) имеют тип `UTF-8 String Pair`.
> Сервер адаптирован для работы с разными реализациями.
>
> 📖 Подробное описание форматов, fallback-механизмов и рекомендаций для разных клиентских библиотек
> см. в [`docs/correlation-data-guide.md`](./correlation-data-guide.md).

В нашем протоколе:
- `correlation_data` (`correlationData`) — **уникальный UUID**, проходящий через все этапы одного RPC-вызова.
- Используется для связывания:
    - `tsk` ↔ `req` (если используется)
    - `req` ↔ `rsp`
    - `res` ↔ `cmt`
    
- Позволяет серверу и клиенту восстанавливать контекст без хранения состояния.

#### Особенности нативной адаптации Correlation Data в брокере RabbitMQ

> 📖 Подробная таблица маппинга типов `correlation_id` (utf8, uuid, ulong, binary) при трансляции MQTT 5 ↔ AMQP 0.9.1 — см. [`correlation-data-guide.md`](./correlation-data-guide.md).

---

### 🏷️ User Properties RPC (MQTT 5)

| Свойство | Направление | Описание |
|---------|------------|--------|
| `method_code` | `tsk`, `rsp` | Код команды (например, `69` — открыть) |
| `status_code` | `res` | Результат выполнения: `200`, `500`, `206` и др. |
| `ext_id` | `res`, `cmt` | Внешний ID задачи |
| `result_id` | `cmt` | ID результата (подтверждение обработки) |
| `result_uid` | `res`, `cmt` | UUID логического результата; для новых устройств обязателен, при повторной отправке не меняется |

Для старых устройств без `result_uid` сервер распознаёт повтор по совокупности
`task_id`, `ext_id`, заголовка `status_code` и нормализованного JSON-результата.
Одинаковые результаты с одинаковыми метаданными будут считаться повтором.
Некорректный `result_uid` обрабатывается как отсутствующий. Если один UID
пришёл с разным содержимым, сохраняется первый результат и повторяется его
`cmt` с прежним `result_id`; сервер фиксирует конфликт в журнале.
Приоритет `status_code` имеет MQTT-заголовок, даже если поле с тем же именем
есть внутри JSON.

Результат после истечения задачи сохраняется и подтверждается `cmt`, статус
остаётся `EXPIRED`. Новый результат, полученный сервером не позднее трёх минут
после внутреннего срока истечения, создаёт обычное сообщение webhook. Дубликат
его не создаёт. После `DELETE` результат также сохраняется и подтверждается,
но webhook не создаётся и статус остаётся `DELETED`. Подробнее: [`TTL.md`](./TTL.md).

---

## 💬 Примеры обмена

### Пример 1: RPC по инициативе сервера (Trigger)

```text
1. Сервер → Устройство (tsk):
   topic: srv/a3b1234567c10221d290825/tsk
   correlationData: a1b2c3d4-...
   userProperty: method_code=51
   (только method_code и конкретный correlationData, без параметров задачи)

2. Устройство → Сервер (ack):
   topic: srv/a3b1234567c10221d290825/ack
   correlationData: a1b2c3d4-...
   (опционально, допускается пропуск этого сообщения и переход к req)

3. Устройство → Сервер (req):
   topic: dev/a3b1234567c10221d290825/req
   correlationData: a1b2c3d4-...
   (наличие в этом запросе конкретного значения correlation data обязательно!)
   
4. Сервер → Устройство (rsp):
   topic: srv/a3b1234567c10221d290825/rsp
   correlationData: a1b2c3d4-...
   userProperty: method_code=51
   payload: {"dt":[{"cl": 5}]}
   (передаются метод и параметры задачи)
   
5. Устройство → Сервер (res):
   topic: dev/a3b1234567c10221d290825/res
   correlationData: a1b2c3d4-...
   userProperty: status_code=200, ext_id=12345
   payload: {"result": "ok"}

6. Сервер → Устройство (cmt):
   topic: srv/a3b1234567c10221d290825/cmt
   correlationData: a1b2c3d4-...
   userProperty: result_id=67890
```


### Пример 2: RPC по инициативе устройста (Polling)

```text
1. Устройство → Сервер (req):
   topic: dev/a3b1234567c10221d290825/req
   correlationData: 00000000-...

2. Сервер → Устройство (rsp):
   topic: srv/a3b1234567c10221d290825/rsp
   correlationData: a1b2c3d4-...
   userProperty: method_code=51
   payload: {"dt":[{"cl": 5}]}

3. Устройство → Сервер (res):
   topic: dev/a3b1234567c10221d290825/res
   correlationData: a1b2c3d4-...
   userProperty: status_code=200, ext_id=12345
   payload: {"result": "ok"}

4. Сервер → Устройство (cmt):
   topic: srv/a3b1234567c10221d290825/cmt
   correlationData: a1b2c3d4-...
   userProperty: result_id=67890
```

Порядок выбора задачи для шага `req(UUID(0)) -> rsp`: см. [`TTL.md`](./TTL.md) — единый источник правил поллинга.

### Пример 3: `method_code=17` — кейс `UI-Catalog` для `l4-hmi`

```text
Сервер → Устройство (rsp):
   topic: srv/a3b1234567c10221d290825/rsp
   correlationData: a1b2c3d4-...
   userProperty: method_code=17
   payload: {"dt":[{"scope":"catalog","url":"https://example.com/ui/catalog.json"}]}
```

> 📌 Этот payload использует тот же транспортный RPC-flow, что и остальные вызовы.
> 🆕 Для `l4-hmi` детализированный итог обновления UI-каталога может прийти отдельным событием `event_type_code = 70` с тегами `401`–`410` — см. [`event-types-reference.md`](./event-types-reference.md) и [`event-property-tags.md`](./event-property-tags.md).

---

## ⚠️ Известные риски и граничные случаи

### Race condition при выборке задачи (Task Selection Race)

**Описание сценария:**

Ситуация возникает при совместном использовании **Trigger** и **Polling** механизмов, когда сервер получает некорректный (или пустой) `res` от устройства.

**Пример из логов (реальный инцидент):**

```text
16:16:17 — Сервер публикует задачу через tsk (Trigger), status=1 (pending)
16:16:17 — Устройство отправляет req с конкретным UUID (Trigger-сценарий)
16:16:17 — Сервер возвращает rsp с параметрами задачи (status=1)
16:16:18 — Сервер получает res с пустым status_code (некорректный ответ)
16:16:24 — Устройство отправляет polling req с нулевым UUID (00000000-...)
16:16:24 — Сервер повторно выбирает ту же задачу (status=2, locked)
16:16:24 — Сервер повторно публикует rsp с той же задачей
16:16:25 — Сервер снова получает res с пустым status_code
```

**Механизм возникновения:**

Если устройство выполнило `req → rsp` по Trigger-сценарию и отправило `res`, но сервер не смог корректно обработать ответ (пустой/невалидный `status_code`), задача **остаётся в статусе, доступном для повторной выборки**. При следующем polling-запросе (`req` с нулевым UUID) сервер снова вернёт эту задачу.

**Последствия:**

- Устройство может получить одну и ту же задачу **дважды** — один раз через Trigger, второй через Polling.
- Если задача уже была выполнена устройством, повторная доставка создаёт риск **двойного выполнения** (double execution).

**Поведение по сторонам:**

| Сторона | Ситуация | Поведение |
|---------|----------|-----------|
| **Сервер** | Получен некорректный / пустой `res` | Задача остаётся доступной для поллинга; изменение протокола без расширения не позволяет это исправить |
| **Сервер** | `res` не получен вовсе | Задача протухнет по TTL или будет повторно доставлена через поллинг |
| **Устройство** | Задача получена повторно | Устройство **должно** контролировать идемпотентность выполнения |

**Рекомендации для реализации клиента (устройства):**

1. **Идемпотентность** — перед выполнением задачи устройство должно проверять, не была ли задача с данным `correlation_data` (UUID) уже выполнена. Рекомендуется хранить журнал обработанных `correlation_data` на период TTL задачи.
2. **Валидность `res`** — устройство должно отправлять `res` только с корректным непустым `status_code`. Пустой или невалидный ответ воспринимается сервером как сбой и не закрывает жизненный цикл задачи.
3. **Повторная доставка — не ошибка протокола** — задача может быть доставлена повторно при использовании Polling после неудачного Trigger-цикла. Это штатное поведение системы, а не баг.

> 💡 **Итог:** на стороне сервера данный сценарий не требует изменений кода и расширения протокола. Ответственность за идемпотентность исполнения лежит на **устройстве**.

---

## 🔖 Серийный номер устройства SN

- Используется строго заданный в сертификате реквизит CN (Common Name)
- Устройству выдается соответствующий сертификат
- Этот же sn используется для параметра client_id в свойствах подключения (при создании соединения) протокола mqtts.

---

## 🔐 Безопасность

- **TLS 1.2+** с проверкой сертификатов сервера и клиента
- Шифрование данных при передаче
- Аутентификация клиента по сертификату (`certificate` + `private key`)
- Проверка имени хоста (`COMMON_NAME`)
- CA-сертификат для валидации сервера
- Уникальный `client_id` = серийный номер устройства (`CN`, `COMMON_NAME` сертификата).

---

## ⏱️ Таймеры и фоновые процессы, рекомендуемые для клиента

| Таймер | Период | Назначение |
|-------|-------|-----------|
| `req_poll_timer` | Конфигурируемый (напр., 60 сек) | Периодическая отправка `req` для опроса задач |

---

## ✅ Заключение

Данный протокол обеспечивает:
- Гибкий механизм RPC с поддержкой поллинга и триггеров
- Сквозную корреляцию через `correlation_data`
- Совместимость с MQTT 5
- Надёжность, безопасность и масштабируемость

Он идеально подходит для IoT-устройств, требующих двустороннего взаимодействия с облачной платформой.

---

## 📚 Связанные документы

| Файл | Назначение |
| :-- | :-- |
| [`mqtt-rpc-client-flow.md`](./mqtt-rpc-client-flow.md) | 📊 **Графическая реплика протокола** (Mermaid-диаграммы): Polling, Trigger, Fail-fast, сводная топик-карта. Должна актуализироваться вслед за изменениями в данном файле. |
| [`mqtt-rpc-correlation-matrix.md`](./mqtt-rpc-correlation-matrix.md) | Сводная матрица: где и как передаётся `correlationData` в протоколе и текущей реализации |
| [`correlation-data-guide.md`](./correlation-data-guide.md) | Руководство по Correlation Data: форматы, fallback-механизмы, рекомендации для разных клиентских библиотек |
| [`TTL.md`](./TTL.md) | TTL: единица измерения, декремент, поведение при TTL=0, исключение из поллинга |
| [`method-codes-reference.md`](./method-codes-reference.md) | Реестр `method_code`: диапазоны, форматы `payload.dt`, ответы `res` для каждой команды |
| [`remote-diagnostics-protocol.md`](./remote-diagnostics-protocol.md) | Remote diagnostics / live logs через `dev/<SN>/out` и RPC-коды `7000..7002` |
| [`1-task-workflow-doc.md`](./1-task-workflow-doc.md) | REST API: workflow задач через HTTP, жизненный цикл, форматы запросов и ответов |
| [event-protocol-mqtt.md](https://github.com/OlegLebedevRU/iot-rpc-rest-app/blob/master/docs/event-protocol-mqtt.md) | Протокол асинхронных событий: топики `evt`/`eva`, формат событий и теги `3xx` |
| [`server-integration-guide.md`](./server-integration-guide.md) | Руководство по интеграции серверной стороны с IoT RPC |

## 2026-10-04: diagnostic payload and TSK execution gate

TaskCreate validates methods 7000–7002 before persistence. The payload is exactly
{"dt": [...]}: items must match the selected method. 7000 and 7001 require one
object. 7002 allows one session-addressed object or an empty array to cancel the
current exclusive command. Other deployed methods, including 7010, retain their
contracts and are not reinterpreted by this validator.

TSK adds payload_required (default true), also a MQTT User Property with values
1/0. Canonical empty 7002 and 7003 use false (Ping has no mutating side effect). Missing flags mean wait for RSP.
A consumer may execute that empty Cancel on TSK, then complete req/rsp/res/cmt
without executing again on RSP. Addressed Cancel and Exec wait for payload.

IoT generates the task UUID (response id). Method is header.method_code and MQTT
User Property method_code; correlationData carries the same task UUID. RES must
set transport User Properties status_code and result_uid: a JSON status alone
does not set persisted result status. RPC logs redact PIN-like fields recursively
without changing delivery payload. Cancel dispatch retains the output forwarder
until terminal EOF or the original session deadline. A websocket output send
wait is bounded to five seconds or remaining session time.

## RPC7011 — authenticated certificate renewal (2026-10-04)

TaskCreate validates payload.dt as exactly one object with pin (six ASCII digits),
pin_expires_at (UTC epoch seconds from PB expires_at), and ttl_sec (120).
Unknown fields are rejected. The queued task UUID is generated by IoT.
TTL is positive minutes and cannot exceed remaining PIN lifetime; persistence
also clamps the absolute deadline to PIN expiry. 7011 always waits for RSP.
Delivery goes through the existing tsk/req/rsp/res/cmt topics, QoS as above,
without retain or a second HTTPS PIN-fetch endpoint.

A zero-correlation REQ may advertise MQTT User Property rpc_methods with a
comma-separated subset of 7001,7002,7003,7011. Selection filters those methods,
so service reconnect polling cannot consume a main application's legacy tasks.
Absent/invalid capability headers retain the existing legacy polling limit.
The native consumer polls on reconnect, then sparsely while idle; periodic
polling and task/result retry timing are part of its consumer contract.

RPC logs and result history recursively redact sensitive keys. The delivery PIN
is retained only in the task payload: result commit, task deletion and the
existing expiration job scrub renewal payload to {"dt":[]}. No new sweep job,
operation UUID or task-creation outbox is introduced. Existing result webhook
transactions remain unchanged. Event75 already reports installed certificate
serial/thumbprint/expiry; use it and existing result triggers for reconciliation,
with an explicit UI check when necessary. Neither events nor RES contain PINs.

### Delivery versus authorized history (2026-10-05)

Authorized REST task detail includes payload with recursive credential redaction;
raw payload remains only in MQTT task delivery. Results, webhook and metadata
logging never expose renewal PIN. Entire l4pin command_line is masked too,
including manual-console PIN arguments. SQLAlchemy engine hides bound parameters.
Stored status_code is taken from MQTT User Properties, so l4con must emit the
property as well as its JSON body. A used PIN is issuance, not proof of store
installation: fresh PB mTLS discovery of the current serial provides confirmation.


## L4FM v2 — результат интеграции 2026-10-05

FM start/renew используют RPC7023, transfer —7021. RPC7020/7022/7023-stop
отклоняются. Navigation и confirmed stop вынесены в srv/{SN}/fmc → dev/{SN}/fmr,
v=2, command_id/lease_id/TTL, no retain; bytes/URL S3 не идут через MQTT.
Корреляция pending/reply через Redis общая для app workers; reply до64entries/24КиБ,
ожидание7с. [Контракт, shared lease, topology и runtime evidence](file-manager-v2.md).
# Transport-only channel probe

The separately marked orphan REQ/RSP and fresh EVT/EVA extension is described in
[channel-probe.md](channel-probe.md). It bypasses task/event persistence and
billing without changing ordinary RPC semantics. No RPC command is accepted.

L4Con capability polling supports7001/7002/7003/7011/7021/7023/7030–7033.
Retired7020/7022 are not current capabilities. Addressed703x remains in the
existing <=7099 trigger range. A completed addressed task still returns ordinary
NOP with zero correlation, so ordinary NOP alone does not provide a nonce barrier.
