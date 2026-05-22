# LEO4 как vendor execution layer для постаматов и ячеек: три архитектурных режима

## Executive summary

LEO4 может использоваться как **vendor execution layer** для управления контроллерами, замками и событиями, при этом бизнес-логика (пользователи, заказы, оплаты, тарифы, поддержка) остаётся в системе клиента.

Для пресейла фиксируются **ровно три допустимых архитектурных режима**:

1. **Local-only mode** — без Leo4 IoT Platform, локальный `Local device-agent` работает как микробэкенд рядом с контроллером.
2. **Cloud-orchestrated mode** — контроллер подключён только через Leo4 IoT Platform, оркестрация идёт через облачный контур.
3. **Hybrid mode** — часть команд идёт через облако, часть локально; граница определяется проектной policy.

Критически важно: `status=3 (DONE)` подтверждает завершение RPC/task-цикла, но **не** подтверждает физическое действие. Физический результат подтверждается только событиями (`event_type_code=13/14`, а также контекстно `3/63/44`).

> [!IMPORTANT]
> Подтверждено текущими docs: RPC/REST task-flow, event-flow, MQTT topic model, correlation data, webhooks, TTL, идемпотентность и подтверждение физики через события.
>
> Не фиксируем неподтверждённые обещания в этом документе: SLA/licensing, точные offline buffer limits, коммерческие условия.

## Голос клиента: ключевые цитаты из заявки

> «Нам интересен продукт Виоланты / LEO4 как технический слой управления оборудованием: контроллеры, замки, события, online/offline, безопасность, API и поддержка.»

> «Бизнес-логика остается в нашей системе.»

> «Нам нужно понять, можно ли использовать LEO4 как vendor execution layer, подключенный к нашему локальному device-agent.»

> «Может ли LEO4 открыть ячейку без участия нашего device-agent?»

> «Можно ли настроить схему так, чтобы все команды открытия проходили только через наш device-agent / наш adapter?»

> «Если используется облачный LEO4, может ли ваше облако отправить команду открытия напрямую в контроллер, минуя наш device-agent?»

> «Offline нужен только для уже разрешенных операций.»

> «Мы хотим использовать собственный интерфейс на экране устройства.»

## Позиционирование решения

- **LEO4 Controller Layer (локально):** hardware execution (команды замкам, чтение датчиков, статусы каналов).
- **Local `device-agent` (опционально):** локальный orchestration/enforcement слой клиента.
- **Customer Business Cloud:** master-система бизнес-правил, авторизации и аудита клиента.
- **Leo4 IoT Platform (опционально, зависит от режима):** REST + MQTT RPC + Events API + Webhooks + история событий.

Ключевая мысль для клиента: LEO4 остаётся техническим execution/event слоем, а бизнес-решения и policy ownership могут оставаться у клиента во всех трёх режимах.

## Трёхуровневая архитектура

Логические уровни одинаковы, но включаются по-разному в каждом режиме:

1. **Orchestration/policy layer** — customer cloud и/или local device-agent.
2. **Transport/control layer** — Leo4 IoT Platform (в cloud- и hybrid-режиме) и/или локальный REST контроллера (в local/hybrid).
3. **Execution layer** — LEO4 controller + Т-16 + locks/sensors.

```mermaid
flowchart TD
    A[Orchestration and Policy Layer] --> B[Transport and Control Layer]
    B --> C[Execution Layer]

    A1[Customer Business Cloud]
    A2[Local device-agent]
    B1[Leo4 IoT Platform REST or MQTT RPC]
    B2[Controller Local REST API]
    C1[LEO4 Controller]
    C2[T-16 Locks Sensors]

    A --- A1
    A --- A2
    B --- B1
    B --- B2
    C --- C1
    C --- C2
```

## Ответ на главный security-вопрос: можно ли исключить обход device-agent?

Да, но ответ зависит от выбранного режима:

- **Local-only:** обход cloud-контура исключён архитектурно (облако Leo4 не используется).
- **Cloud-orchestrated:** обязательный путь через Leo4 IoT Platform; запрет обхода задаётся cloud ACL/policy и маршрутизацией.
- **Hybrid:** обход исключается только при чётком контракте маршрутизации классов команд + строгом ACL/policy + едином audit/reconcile.

Во всех режимах критичные unlock-capable команды должны быть управляемы policy:
`51`, `16`, `35`, `47/26`, `18/42/48`, `49/50` (см. [`../method-codes-reference.md`](../method-codes-reference.md)).

## Три жёстких архитектурных кейса

### 1) Local-only mode (без Leo4 IoT Platform)

**Что это:** Leo4 IoT Platform не используется. `Local device-agent` выступает полноценным микробэкендом рядом с контроллером LEO4.

**Интеграция:** `Local device-agent` ↔ `LEO4 Controller` через локальный REST API (endpoint'ы подняты на контроллере).

**Ориентир по локальному web-flow:** в `OlegLebedevRU/siplite` более развитая локальная модель показана в `main/leo4_web.c`:
- `esp_start_webserver()` регистрирует `/gate` (WebSocket), `/event`, `/task`, `/nvs`;
- поток `leo4_web.c -> /task -> /event -> /nvs` описан в `docs/event_web_architecture_analysis.md`;
- `/task` и `/event` несут task/result/event семантику, `/gate` работает как gateway/live-channel.

Следствие для пресейла: если в локальном REST не хватает отдельных RPC-режимов, они могут быть быстро добавлены локально как новые REST endpoints/handlers по аналогии с этим web-flow, **без обязательного подключения Leo4 IoT Platform**.

```mermaid
sequenceDiagram
    participant BC as Customer Business Cloud
    participant AG as Local device-agent
    participant CT as LEO4 Controller Local REST
    participant HW as T-16 Locks Sensors

    BC->>AG: authorize operation
    AG->>CT: POST local REST task method_code=51 or 16 or 35
    CT->>HW: execute command on lock controller
    HW-->>CT: sensor feedback
    CT-->>AG: local task result status=3 DONE
    CT-->>AG: local events 13 or 14 or 3 or 63 or 44
    AG-->>BC: audit and business result
```

### 2) Cloud-orchestrated mode (через Leo4 IoT Platform)

**Что это:** LEO4 controller подключён только через Leo4 IoT Platform. `Local device-agent`, если используется как оркестратор клиента, подключается архитектурно через cloud, а не напрямую к REST контроллера.

**Command path (обязательный):**
Customer Business Cloud / Local device-agent-orchestrator → Leo4 IoT Platform → MQTT RPC → LEO4 Controller → T-16/locks/sensors.

Cloud здесь является обязательным control-plane/data-plane посредником для команд и событий.

```mermaid
sequenceDiagram
    participant BC as Customer Business Cloud
    participant AG as Local device-agent orchestrator
    participant LP as Leo4 IoT Platform
    participant CT as LEO4 Controller
    participant HW as T-16 Locks Sensors

    BC->>AG: business authorization
    AG->>LP: REST task create method_code=51 or 16 or 35
    LP->>CT: MQTT RPC task request
    CT->>HW: execute physical command
    HW-->>CT: physical state change
    CT-->>LP: task response status=3 DONE
    CT-->>LP: events 13 or 14 or 3 or 63 or 44
    LP-->>AG: task status and events stream
    AG-->>BC: physical confirmation by events only
```

### 3) Hybrid mode (cloud + local orchestration)

**Что это:** часть оркестрации выполняется у клиента через cloud + Leo4 IoT Platform, часть — локально через `Local device-agent` и REST API контроллера LEO4.

**Обязательная граница:** классы команд, идущие через cloud и локально, фиксируются проектным контрактом/policy.

Типовой пример разделения (иллюстративно, финализируется контрактом):
- **Cloud path:** удалённые операции, межсайтовая оркестрация, централизованный аудит, массовые обновления (`16`, `47/26`, часть `49/50`).
- **Local path:** latency-sensitive операции на точке, pre-authorized offline-процедуры, локальные fallback-сценарии (`51`, `35`, часть `18/42/48` по ACL).

Hybrid требует:
- строгой маршрутизации команд (no-ambiguity routing);
- ACL/policy для всех unlock-capable method codes;
- единого event/audit/reconcile подхода, чтобы исключить bypass и расхождения состояний.

```mermaid
flowchart LR
    BC[Customer Business Cloud] --> AG[Local device-agent]
    BC --> LP[Leo4 IoT Platform]
    AG --> CT[LEO4 Controller Local REST]
    LP --> CT2[LEO4 Controller MQTT RPC]
    CT --> HW[T-16 Locks Sensors]
    CT2 --> HW

    P[Policy Router and ACL] -. governs .-> AG
    P -. governs .-> LP
    E[Unified Event Audit Reconcile] -. collects .-> AG
    E -. collects .-> LP
```

## Deployment-модели

### Сравнительная таблица трёх режимов

| Режим | Где исполняется orchestration | Используется ли Leo4 IoT Platform | Command path | Где живёт security boundary | Как доставляются/собираются events | Offline-возможности | Основной риск/условие |
|---|---|---|---|---|---|---|---|
| **Local-only** | У клиента в `Local device-agent` (локальный микробэкенд) | Нет | `Customer Cloud -> Local device-agent -> Local REST Controller -> T-16/locks` | Локально: agent + controller ACL | Локальные event endpoints/каналы + клиентский сбор/аудит | Максимальные для pre-authorized и локальных сценариев | Нужно явно поддерживать нужные RPC-режимы в локальном REST API |
| **Cloud-orchestrated** | В customer cloud orchestration + Leo4 IoT Platform control plane | Да, обязательно | `Customer Cloud or Local orchestrator -> Leo4 Platform -> MQTT RPC -> Controller -> T-16/locks` | Cloud routing + ACL/policy + onboarding endpoint rules | Events API, webhooks, MQTT `evt/eva`, history в platform | Ограничены архитектурой cloud-пути; offline только по согласованной модели | Риск зависимости от cloud connectivity и требований к cloud governance |
| **Hybrid** | Разделено между cloud и local по policy | Да, частично (для cloud-класса команд) | Два разрешённых пути: cloud-path и local-path по контракту | Двойная граница: policy router + ACL на обоих путях | Единый event/audit/reconcile поверх cloud+local источников | Высокие для локально разрешённых классов команд | Главный риск — рассинхронизация и bypass без строгого policy-контракта |

## Контроль method codes по policy

Ниже — какие команды обязательно должны попадать в policy-контур (во всех трёх режимах):

- **Direct open:** `51`.
- **PIN/access:** `16`, `35`, `47`, `26`.
- **Raw/control-sensitive:** `18`, `42`, `48`.
- **NVS/config:** `49`, `50`.

Практическое правило для пресейла: даже если команда не открывает ячейку напрямую, она должна классифицироваться как unlock-capable, если может изменить доступы, ввод, поведение портов или конфигурацию.

## События, статусы и подтверждение физического результата

- `status=3 (DONE)` = завершение task/RPC-цикла, **не** физическое подтверждение выполнения.
- Физическое открытие подтверждается `event_type_code=13` (`CellOpenEvent`).
- Физическое закрытие подтверждается `event_type_code=14`.
- Ввод идентификатора/PIN/RFID: `event_type_code=3`.
- Full state: `event_type_code=63`.
- Keep-alive/status: `event_type_code=44`.

> [!WARNING]
> Для бизнес-процесса «успех операции» подтверждение должно опираться на события, а не только на DONE-статус.

## Надёжность доставки, идемпотентность и replay

- Для MQTT `evt`: рекомендуемый QoS 1.
- Серверное подтверждение при обработке события: `srv/<SN>/eva`.
- Dedupe: `(device_id, dev_event_id, dev_timestamp)`.
- Incremental replay/polling: через `last_event_id`.
- Webhook retry: по стратегии из профильной документации.

## Offline-сценарий

Рекомендуемый контур (без фиксации неподтверждённых лимитов):

1. Pre-authorized доступы загружаются заранее (`16` и связанные команды policy).
2. Local allow-list применяется в разрешённом policy-контуре.
3. При потере внешней связи выполняются только заранее разрешённые операции.
4. Технические события буферизуются локально/промежуточно по выбранной архитектуре.
5. После восстановления связи выполняется sync + dedupe + reconcile + webhook/API доставка.

> [!NOTE]
> Конкретные offline buffer limits и conflict-resolution policy фиксируются отдельным техконтрактом.

## Kiosk UI

- Клиент может использовать **собственный kiosk UI**.
- LEO4 может работать в headless-модели как технический execution/event слой.
- LEO4 HMI (`И-4` / `И-7`) — опционально.

## Минимальный тестовый стенд

- LEO4 controller (У-1).
- Плата Т-16.
- 1 физический замок.
- 1 датчик/концевик открытия-закрытия.
- Питание.
- API-доступ (REST/MQTT по договорённости).
- `device_id` / `SN` / сертификатная идентичность.
- Опционально mini-PC с `Local device-agent`.

## Тест-план (по трём режимам)

1. Проверка выбранного режима (Local-only / Cloud-orchestrated / Hybrid) и документированной маршрутизации.
2. Direct open (`51`) по разрешённому пути.
3. PIN-flow (`16`, `35`, `47/26`) по policy.
4. Проверка `DONE` vs физическое подтверждение по `event_type_code=13/14`.
5. Проверка `event_type_code=3/63/44` для audit/state/health.
6. Error/timeout и retry сценарии.
7. Offline/reconnect для разрешённых операций.
8. Проверка, что запрещённый путь (bypass) блокируется ACL/policy.
9. Для Hybrid — проверка reconcile и отсутствия рассинхронизации между cloud/local event sources.

## Матрица соответствия требованиям клиента

| Пункт заявки | Что требуется | Ответ |
|---|---|---|
| 1 | Command path / bypass risk | Поддерживаются три жёстких режима; запрет bypass достигается архитектурой + ACL/policy |
| 2 | LEO4 как technical layer без бизнес-логики | Да, бизнес-логика остаётся у клиента во всех трёх режимах |
| 3 | События и статусы | Поддерживаются события открытия/закрытия/input/full state/health + API/webhooks |
| 4 | Offline только для разрешённых операций | Реализуемо через pre-authorized доступы и policy-контур |
| 5 | Deployment-варианты | Формально фиксированы Local-only, Cloud-orchestrated, Hybrid |
| 6 | Собственный kiosk UI | Да, возможна headless-модель LEO4 + клиентский UI |
| 7 | API и документация | Есть REST/MQTT/event/webhook документы; credentials и стенд — по согласованной процедуре |
| 8 | Минимальный стенд | У-1 + Т-16 + lock + sensor + power + API доступ + опциональный local agent |
| 9 | Что проверить на тесте | Сформирован тест-план под три режима и policy/bypass проверки |
| 10 | Коммерческая модель | SLA/licensing/support финализируются на пресейл/контрактном этапе |
| 11 | Критичные условия безопасности | Контролируемые method codes + `DONE != physical execution` + event-based confirmation |
| 12 | Желаемый результат | Есть ясная архитектурная карта из трёх режимов и список решений для техзвонка |

## Что нужно финализировать на техническом звонке

1. Какой из трёх режимов фиксируется для проекта (Local-only, Cloud-orchestrated, Hybrid).
2. Для Hybrid: формальный boundary командных классов между cloud-path и local-path.
3. Матрица ACL/policy по method codes (`51`, `16`, `35`, `47/26`, `18/42/48`, `49/50`).
4. Правила reconcile/event-audit для hybrid-маршрутизации.
5. Детали PIN overwrite и lifecycle access-данных.
6. Offline buffer limits и conflict resolution policy после reconnect.
7. SLA/licensing/support модель.
8. Выдача тестовых credentials/device-профиля.
9. Единый критерий «команда доставлена» vs «физическое действие подтверждено» (`DONE` vs events).

## Рекомендованная формулировка ответа клиенту

> Мы подтверждаем, что LEO4 может использоваться как vendor execution layer для контроллеров/замков/событий без переноса вашей бизнес-логики в LEO4.  
> Для проекта доступны три архитектурных режима: **Local-only**, **Cloud-orchestrated**, **Hybrid**.  
> В Local-only режиме Leo4 IoT Platform не требуется: локальный `Local device-agent` работает как микробэкенд и взаимодействует с контроллером через локальный REST API.  
> В Cloud-orchestrated режиме команды и события идут через Leo4 IoT Platform как обязательный control-plane/data-plane.  
> В Hybrid режиме маршрутизация команд делится между cloud и local по заранее согласованной policy, с обязательными ACL и единым event/audit/reconcile контуром.  
> Во всех режимах `status=3 (DONE)` трактуется как завершение task/RPC цикла, а физическое выполнение подтверждается только событиями (`event_type_code=13/14`, плюс `3/63/44` для контекста).

## Контроллерный контур Leo4/T-16 (смежные материалы)

С учётом материалов из внешнего репозитория `docs_mirror/controllers`:

- Leo4 ПАК включает У-1, Т-16, И-4/И-7 и опциональные ридеры/QR/замки/БП.
- Т-16: 16 каналов управления замками с датчиками.
- Несколько Т-16 объединяются по RS-485 до массива 256 замков.
- Т-16 исполняет команду открытия от У-1 по RS-485.
- Есть команда «запрос статуса», ответ возвращает битовые поля датчиков каналов.
- Для У-1 задокументированы режимы MQTT(S)-client, WS/Web server и режим с персистентной очередью событий.

> ⚠️ Эти пункты основаны на смежных controller docs (`docs_mirror`) и должны быть финально зафиксированы в проектном контракте поставки/интеграции.

## Ссылки на документацию

### Внутренние документы репозитория

- [`../mqtt-rpc-protocol.md`](../mqtt-rpc-protocol.md)
- [`../1-task-workflow-doc.md`](../1-task-workflow-doc.md)
- [`../task_states.md`](../task_states.md)
- [`../event-protocol-mqtt.md`](../event-protocol-mqtt.md)
- [`../2-events-api-format-description.md`](../2-events-api-format-description.md)
- [`../3-webhooks.md`](../3-webhooks.md)
- [`../method-codes-reference.md`](../method-codes-reference.md)
- [`../event-types-reference.md`](../event-types-reference.md)
- [`../event-property-tags.md`](../event-property-tags.md)
- [`../correlation-data-guide.md`](../correlation-data-guide.md)
- [`../mqtt_topic_rules.md`](../mqtt_topic_rules.md)
- [`../TTL.md`](../TTL.md)
- [`../server-integration-guide.md`](../server-integration-guide.md)

### Смежные материалы по локальному web-flow (siplite)

- [`OlegLebedevRU/siplite/main/leo4_web.c`](https://github.com/OlegLebedevRU/siplite/blob/master/main/leo4_web.c)
- [`OlegLebedevRU/siplite/docs/event_web_architecture_analysis.md`](https://github.com/OlegLebedevRU/siplite/blob/master/docs/event_web_architecture_analysis.md)
- [`OlegLebedevRU/siplite/docs/api.md`](https://github.com/OlegLebedevRU/siplite/blob/master/docs/api.md)
- [`OlegLebedevRU/siplite/docs/dashboard-developer-guide.md`](https://github.com/OlegLebedevRU/siplite/blob/master/docs/dashboard-developer-guide.md)

### Смежные материалы по контроллерам

- [`OlegLebedevRU/docs_mirror/controllers/Leo4-controllers-description.md`](https://github.com/OlegLebedevRU/docs_mirror/blob/master/controllers/Leo4-controllers-description.md)
- [`OlegLebedevRU/docs_mirror/controllers/Description_Leo4_T-16.md`](https://github.com/OlegLebedevRU/docs_mirror/blob/master/controllers/Description_Leo4_T-16.md)
