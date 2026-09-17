# Архитектура коммерческого сервиса удалённого управления L4Desk

**Статус:** финальный архитектурный документ для MVP  
**Дата:** 2026-09-17  
**Каталог сервиса:** `l4desk-service`  
**Владелец коммерческого контура:** `MenuBuilder`  
**Владелец device/RPC-контура:** `iot-rpc-rest-app`  

## 1. Резюме решения

L4Desk — коммерческий SaaS для консоли, видеонаблюдения и удалённого управления компьютерами через браузер. Решение не создаёт новый параллельный стек, а коммерциализирует и объединяет существующие возможности:

- `MenuBuilder` — регистрация, tenant/user UX, терминалы, лицензии, entitlement, платежи, финансовый subledger и Хаб;
- `iot-rpc-rest-app` — реестр устройств, RabbitMQ/MQTT, RPC-задачи и результаты, фактические состояния удалённых сессий;
- `tools` и Агент — установка на ПК, сертификат, MQTT/RPC и выполнение удалённых команд;
- `ProcessingBackend.certificates` — PIN, CSR, выпуск и аудит сертификатов;
- `l4media` — защищённая on-demand передача экрана через WebRTC;
- ЮKassa — пополнение внутреннего баланса физических лиц;
- PostgreSQL `MenuBuilder` — единственный источник истины финансового subledger.

MVP строится без новых микросервисов, Kafka и полного event sourcing. Используются существующие backends, PostgreSQL, текущая RabbitMQ/MQTT-инфраструктура IoT-проекта и небольшие фоновые worker-задачи.

## 2. Цели и границы MVP

### 2.1. В MVP входят

1. Публичная саморегистрация с подтверждением email.
2. Атомарное создание пользователя `role = 5`, tenant и membership владельца.
3. Приглашение дополнительных пользователей tenant; на первом этапе все они имеют `role = 5`.
4. Создание терминалов в `MenuBuilder`, provisioning в `iot-rpc-rest-app` и немедленная выдача одноразового PIN сертификата.
5. Мастер первого подключения: создать терминал, получить PIN, скачать Агент, установить, дождаться online, открыть консоль или видео.
6. Единые существующие реализации консоли, видео и удалённого управления для старых пользователей `MenuBuilder` и нового L4Desk-профиля.
7. Коммерческие тарифы, постоянная льгота первого терминала, внутренняя предоплата и трёхдневная отсрочка блокировки.
8. ЮKassa для физлиц и ручная регистрация банковской оплаты юрлица одним superuser.
9. Финансовый subledger двойной записи, регистры потребления, проекция баланса и сверка.
10. Хаб superuser: регистрации, терминалы, сессии, потребление, лицензии, платежи, проводки, уведомления и ошибки.
11. Email-уведомления до границы цикла и при переходах `grace/blocked`.
12. Помесячная архивация массовой технической истории.
13. MCP-промо-страница и список интереса без реализации удалённых MCP-инструментов.

### 2.2. За пределами MVP

- конструктор автоматизаций `MenuBuilder`;
- задачи `cmd`/`PowerShell` по расписанию;
- групповые задания по парку ПК;
- сложная ролевая модель внутри tenant;
- отдельный billing microservice;
- потоковая аналитическая платформа;
- прозрачные SQL-запросы к архивам;
- полноценная BI-система;
- разработка нового Agent protocol без необходимости.

## 3. Архитектурные принципы

1. **Одна реализация функций.** L4Desk добавляет navigation profile, tenant policy и entitlement вокруг существующих console/video use cases, но не создаёт их копии.
2. **Коммерческое решение отдельно от исполнения.** `MenuBuilder` решает, разрешена ли функция; `iot-rpc-rest-app` решает, возможно ли её технически исполнить.
3. **Финансы только из подтверждённых фактов.** Проводки создаются из device/session/payment facts, а не из текущих флагов UI.
4. **Строгая контрактная граница.** Между проектами нет чтения чужой БД или зависимости от внутренних RabbitMQ-очередей.
5. **Обратная совместимость Агента.** Новая коммерческая логика не меняет смысл существующих MQTT topics, method codes и обязательных payload.
6. **Идемпотентность.** Повтор REST-запроса, IoT-события, webhook или polling не создаёт вторую сессию, оплату или проводку.
7. **Append-only финансы.** Проведённые документы не редактируются; исправления выполняются сторно и корректирующими транзакциями.
8. **Деньги — целые копейки.** `float` запрещён; пользовательские начисления кратны одному рублю.
9. **Timezone фиксируется.** Суточная квота считается по timezone tenant; смена timezone вступает в силу не раньше следующих локальных суток и не переписывает закрытые расчёты.
10. **Небольшая допустимая задержка.** Проверка квоты/баланса выполняется периодически, без посекундного online-биллинга.

## 4. Общая схема компонентов

```text
Внешний лендинг
      │
      ▼
MenuBuilder frontend/backend
  ├─ регистрация, email, tenant, role=5
  ├─ настройки: профиль, терминалы, пользователи
  ├─ единая консоль и видеонаблюдение
  ├─ entitlement, тарифы, fin_* subledger
  ├─ ЮKassa и ручные оплаты
  ├─ Хаб и уведомления
  └─ MCP promo/waitlist
      │
      │ versioned internal REST + service auth
      ▼
iot-rpc-rest-app
  ├─ device registry и provisioning
  ├─ online/presence
  ├─ remote session lock и lifecycle
  ├─ durable event feed
  ├─ RabbitMQ/MQTT topology
  └─ RPC tsk/req/rsp/res/cmt
      │
      │ существующий Agent MQTT/RPC contract
      ▼
Агент из tools на ПК
  ├─ сертификат и presence
  ├─ консоль/RPC
  ├─ keyboard/mouse/remote input
  └─ управление ffmpeg/leo4proxy
      │
      └─ l4media: mTLS tunnel → ingress → Janus → WebRTC → браузер

ProcessingBackend.certificates
  └─ PIN → CSR → X.509 certificate → terminal binding/audit
```

## 5. Владение данными и ответственностью

| Область | Владелец | Ответственность |
|---|---|---|
| User, tenant, membership, role | `MenuBuilder` | Регистрация, email, tenant scope, пользователи |
| Terminal business record | `MenuBuilder` | Принадлежность tenant, имя, порядок, льготный terminal |
| Device runtime record | `iot-rpc-rest-app` | SN, online, Agent version/capabilities, connection state |
| Certificate PIN и X.509 | `ProcessingBackend.certificates` | Выдача, привязка и история сертификата |
| RabbitMQ/MQTT и RPC | `iot-rpc-rest-app` | Topics, очереди, задачи, ответы, correlation |
| Remote session technical state | `iot-rpc-rest-app` | Mutual exclusion, active/closed facts, graceful stop |
| l4media transport | `l4media` | Route, Janus mountpoint, media health и остановка |
| Entitlement | `MenuBuilder` | Free quota, balance, grace, blocked |
| Тариф и usage calculation | `MenuBuilder` | Версия тарифа, daily/monthly calculation |
| Платежи и ledger | `MenuBuilder` | ЮKassa, manual payments, double-entry, balance |
| Agent distribution | `tools`/artifact registry | Публичный последний релиз и инструкция установки |
| Финансовый архивный manifest | `MenuBuilder` | Сверка и связь с проводками |
| IoT/RPC технический архив | `iot-rpc-rest-app` | Пакеты первичных технических деталей |

## 6. Контракты между проектами

### 6.1. `MenuBuilder ↔ iot-rpc-rest-app`

Контракт — versioned internal REST/JSON. RabbitMQ/MQTT остаётся внутренней реализацией IoT-проекта.

Минимальные операции:

```text
POST /api/internal/v1/devices/provision
POST /api/internal/v1/remote-sessions
POST /api/internal/v1/remote-sessions/{id}/stop
GET  /api/internal/v1/remote-sessions/{id}
GET  /api/internal/v1/remote-session-events?after=<cursor>
```

Изменяющий запрос содержит:

- `operation_id` — UUID идемпотентности;
- `contract_version`;
- `tenant_id`, `terminal_id`, IoT `device_id`/SN;
- `session_type = console | video`;
- `requested_by_user_id`;
- end-to-end `correlation_id`.

IoT event feed содержит:

- уникальный `event_id`;
- монотонный `cursor`;
- `occurred_at` в UTC;
- tenant/terminal/device/session identifiers;
- `session_type` и lifecycle state;
- reason/status;
- `operation_id` и `correlation_id`.

Обязательные события:

```text
device_online
remote_session_start_requested
remote_session_active
remote_session_stop_requested
remote_session_closed
remote_session_failed
console_command_started
console_command_completed
console_command_timed_out
```

`MenuBuilder` хранит consumer cursor и повторно читает события после сбоя. Архивирование event feed разрешено только после прохождения границы всеми обязательными consumers.

### 6.2. `Агент ↔ iot-rpc-rest-app`

Сохраняется существующий контракт `tools/leo4proxy`:

- MQTT topics `srv/<SN>/*` и `dev/<SN>/*`;
- RPC lifecycle `tsk → req → rsp → res → cmt`;
- `7000 CMD_DIAG_STREAM_CONTROL`;
- `7001 EXEC`;
- `7002 CANCEL`;
- существующие remote-input и event contracts.

Правила развития:

1. Не менять смысл существующих topics и method codes.
2. Не удалять обязательные поля и не менять их тип.
3. Новые поля только additive/optional.
4. Не передавать Агенту финансовые поля.
5. IoT adapter выбирает payload по Agent version/capabilities.
6. Golden fixtures формируются из `tools/leo4proxy/examples`.
7. Provider tests проверяют текущий опубликованный Агент и новую версию-кандидат.

### 6.3. Версионирование и rollout

1. Provider сначала поддерживает старую и новую версии.
2. Consumer contract tests проходят на новой версии.
3. `MenuBuilder` переключается на новый контракт.
4. Наблюдаемость подтверждает отсутствие старых вызовов.
5. Старый контракт удаляется отдельным согласованным изменением.

## 7. Пользовательские потоки

### 7.1. Регистрация

1. Пользователь открывает публичную форму с внешнего landing.
2. Вводит email и пароль, принимает условия.
3. Создаётся pending registration; email-токен одноразовый, ограниченный по времени и хранится в виде hash.
4. После подтверждения в одной транзакции создаются `User(role=5)`, tenant, owner membership и профиль timezone.
5. Пользователь попадает в мастер первого подключения.
6. До первой успешной оплаты действует только бесплатный пакет.

Для MVP необходимы rate limit, защита от повторной регистрации email, безопасное хранение пароля и аудит подтверждения.

### 7.2. Создание терминала

1. `MenuBuilder` создаёт terminal business record и устойчивый `operation_id`.
2. После commit выполняется идемпотентный provisioning в IoT.
3. Через `ProcessingBackend.certificates` создаётся одноразовый PIN.
4. UI показывает SN, PIN, ссылку на последний артефакт и инструкцию.
5. Пользователь устанавливает Агент вручную.
6. Агент применяет PIN, получает сертификат и подключается к IoT.
7. Первое аутентифицированное presence-событие становится достоверным `device_online`.
8. Хаб связывает registration → terminal → PIN → certificate → IoT online по identifiers/correlation.

Частичный сбой не удаляет terminal: provisioning/PIN получают состояния и повторяются идемпотентно.

### 7.3. Запуск console/video-сессии

1. `MenuBuilder` проверяет tenant scope и entitlement.
2. Создаёт idempotent session reservation.
3. Вызывает IoT internal API.
4. IoT проверяет online и отсутствие другой активной console/video-сессии.
5. IoT захватывает единственный session lock терминала.
6. IoT запускает существующий RPC/stream flow Агента.
7. Для видео `MenuBuilder/l4media` создают route и Janus mountpoint.
8. Тарификация начинается только после `remote_session_active`.
9. Завершение подтверждается `remote_session_closed`; зависшая сессия закрывается watchdog timeout.

Если активна любая console/video-сессия, запуск второй отклоняется. Автоматического вытеснения нет.

### 7.4. Graceful stop

- Видео/remote-control завершается обычным stop-flow при ближайшей проверке.
- Для console при блокировке запрещаются новые команды.
- Текущая команда ожидает `response` или штатный timeout.
- После ответа/timeout сессия закрывается и lock освобождается.
- Должна существовать конечная верхняя граница ожидания, чтобы зависшая команда не отменяла блокировку.

## 8. Тарифы и лицензионная модель

### 8.1. Исходные тарифы MVP

| Ресурс | Цена |
|---|---:|
| Первый терминал tenant | `0 руб./цикл` |
| Каждый следующий terminal, хотя бы раз online в цикле | `100 руб./цикл` |
| Console + video usage | `1 руб./округлённый час/локальные сутки` |
| Бесплатная квота первого терминала | `120 минут/локальные сутки` |

Тарифы хранятся версионированно с `effective_from`. Закрытый период не меняется при последующей смене тарифа.

### 8.2. Первый бесплатный терминал

- Бесплатен самый ранний существующий terminal по устойчивому порядковому номеру.
- При его удалении льгота переходит к следующему по номеру.
- Закрытые usage/ledger документы и уже созданные terminal-month charges не пересчитываются и не возвращаются задним числом.
- Для бесплатного terminal-month создаётся нулевая расчётная строка, чтобы применение льготы было видно в Хабе.

### 8.3. Индивидуальный цикл

Первая успешная оплата ЮKassa или проведённая ручная оплата создаёт якорь `A`.

```text
Pₙ = [add_months(A, n), add_months(A, n + 1))
```

Для якоря 29–31 используется последний существующий день месяца, но исходный anchor day сохраняется для последующих месяцев.

Граница цикла не переносится из-за позднего online или поздней оплаты.

### 8.4. Terminal-month charge

Достоверный факт — первое аутентифицированное `device_online` в текущем индивидуальном цикле. Даже краткое соединение достаточно.

Уникальный ключ:

```text
(terminal_id, billing_cycle_id)
```

Первый online платного терминала создаёт `100 руб.` начисления ровно один раз. Если terminal впервые online после окончания трёхдневной отсрочки и баланс недостаточен, charge всё равно относится к текущему циклу, а коммерческие remote-функции сразу блокируются.

### 8.5. Суточное использование

Для terminal и локальной даты tenant:

```text
V = активные минуты video/remote control
C = активные минуты console
F = 120 минут для первого терминала, иначе 0
Q = V + C
paid_minutes = max(0, Q - F)
paid_hours = ceil(paid_minutes / 60)
daily_charge = paid_hours × 100 копеек
```

Console и video не пересекаются, поэтому `Q` — простая сумма. Breakdown по типам хранится отдельно, но общая льгота и округление применяются один раз.

Если `Q > 120` на первом терминале и баланс/entitlement позволяет платное использование, блокировать сессию запрещено: она продолжается по платному тарифу. При отсутствии первой оплаты платное продолжение невозможно. После первой оплаты недостаточный баланс регулируется grace-правилом.

Сессия, пересекающая локальную полночь, разделяется между двумя локальными датами.

### 8.6. Предоплата и grace

Фиксированного кредитного лимита нет. До первой оплаты grace не предоставляется.

Для каждого цикла:

```text
cycle_start = индивидуальная граница
grace_deadline = cycle_start + 3 календарных дня
```

После проведённого начисления:

```text
если balance >= 0:
    entitlement = active
иначе если now < grace_deadline:
    entitlement = grace
иначе:
    entitlement = blocked
```

Grace привязан к границе цикла, а не к моменту ухода баланса в минус. Если terminal впервые online на пятый день цикла, charge создаётся, но отсрочка уже истекла и при отрицательном балансе remote-функции блокируются сразу.

Поздняя оплата не сдвигает anchor. Потраченные grace-дни входят в уже начавшийся оплачиваемый период.

При `blocked`:

- terminal и Агент могут оставаться online;
- provisioning, сертификат и пополнение баланса доступны;
- новые console/video-сессии запрещены;
- активные сессии завершаются по graceful policy.

### 8.7. Уведомления

Идемпотентные уведомления:

- за `7`, `3` и `1 день` до границы цикла;
- при переходе в `grace`;
- при переходе в `blocked`.

Уникальный ключ:

```text
(tenant_id, billing_cycle_id, notification_type)
```

До границы цикла письмо содержит прогноз terminal-month и рекомендацию пополнить баланс, а не ложное утверждение о уже проведённом начислении.

## 9. Финансовый subledger

### 9.1. Именование

Денежные и расчётные сущности получают единый префикс `fin_`:

```text
fin_accounts
fin_tariff_versions
fin_billing_cycles
fin_usage_daily
fin_terminal_monthly_charges
fin_payments
fin_manual_payments
fin_ledger_transactions
fin_ledger_entries
fin_balance_projections
fin_notification_deliveries
fin_reconciliation_runs
fin_archive_batches
```

Технические IoT/media events не получают `fin_`, но финансовая проекция из них называется `fin_usage_daily`.

### 9.2. Двойная запись

Минимальные проводки:

```text
Получена оплата:
  Dr payment_clearing
  Cr tenant_settlement

Начислено потребление:
  Dr tenant_settlement
  Cr usage_revenue

Сторно/возврат:
  обратная транзакция со ссылкой на исходную
```

Инвариант каждой транзакции:

```text
Σ debit_kopecks = Σ credit_kopecks
```

Баланс tenant:

```text
balance_kopecks = credits(tenant_settlement) - debits(tenant_settlement)
```

Один settlement account естественно может стать отрицательным; отдельный кредитный flow не нужен.

### 9.3. Округление до целого рубля

Округление выполняется один раз после суточного/месячного агрегирования и до ledger:

```text
calculated_kopecks = результат тарификации
posted_kopecks = floor(calculated_kopecks / 100) × 100
discarded_kopecks = calculated_kopecks - posted_kopecks
```

Инварианты:

```text
calculated_kopecks = posted_kopecks + discarded_kopecks
0 <= discarded_kopecks < 100
posted_kopecks % 100 = 0
ledger debit = ledger credit = posted_kopecks
```

Отброшенные копейки:

- сохраняются в расчётном документе и сверке;
- не проводятся в ledger;
- не накапливаются скрыто в следующий период;
- не удаляются отдельно из debit/credit;
- пересчитываются только вместе с исходным расчётным документом.

При текущих ставках итог уже кратен рублю, но правило требуется для будущих тарифов.

### 9.4. Сверка и перерасчёт

`fin_usage_daily` хранит:

```text
source_seconds
video_seconds
console_seconds
free_seconds
billable_seconds
rounded_billable_hours
rate_kopecks
calculated_kopecks
posted_kopecks
discarded_kopecks
tariff_version_id
source_events_hash
```

Постсверка:

```text
Σ calculated = Σ posted + Σ discarded
Σ ledger debit = Σ ledger credit
balance projection = opening + payments - posted charges ± adjustments
```

Открытый расчёт можно пересчитать. После проведения исходные строки и проводки неизменяемы; исправление создаёт delta calculation и новую корректирующую/сторнирующую транзакцию.

### 9.5. Производительность

- active sessions проверяются worker-задачей раз в `1–5 минут`;
- heartbeat не записывается каждую секунду;
- daily usage — одна компактная строка на terminal/date с breakdown;
- terminal-month — одна строка на terminal/cycle;
- balance projection обновляется инкрементально в транзакции проводки;
- UI читает проекцию, а не суммирует ledger;
- сложность worker — `O(N_active_sessions)` и `O(N_changed_daily_rows)`.

Для MVP PostgreSQL и один worker достаточны.

## 10. Платежи

### 10.1. Физлица и ЮKassa

Пользователь пополняет внутренний баланс на выбранную целую сумму рублей.

```text
MenuBuilder создаёт fin_payment
  → POST ЮKassa с Idempotence-Key
  → получает payment_id и confirmation_url
  → redirect пользователя
  → webhook сообщает изменение
  → backend подтверждает payment через API ЮKassa
  → только status=succeeded создаёт ledger transaction
```

`return_url` не является подтверждением оплаты. Webhook — триггер, fallback polling — восстановление. Один `provider_payment_id` создаёт не более одной проводки.

Для чеков сохраняются provider receipt id/status и snapshot отправленных позиций. НДС, предмет расчёта и прочие фискальные параметры задаются конфигурацией после согласования бухгалтерской модели.

### 10.2. Ручная оплата юрлица

Один superuser создаёт неизменяемый `fin_manual_payment`:

- tenant;
- сумма в целых рублях;
- дата поступления;
- номер/назначение документа;
- плательщик;
- комментарий;
- creator user и timestamps;
- ссылка/вложение подтверждения при наличии.

Документ создаёт обычную двойную проводку. Прямое редактирование balance запрещено; ошибка исправляется сторно.

## 11. UX и навигация

### 11.1. Меню пользователя `role = 5`

1. **Видеонаблюдение** — единый существующий video/remote-control экран.
2. **Настройки**:
   - Профиль;
   - Терминалы;
   - Пользователи.
3. **Консоль** — единое существующее управление устройствами.
4. **MCP** — промо, сценарии использования и кнопка интереса/waitlist.
5. **Лицензии** — баланс, пополнение, цикл, quota, usage и детализация.

Одна SPA использует product/navigation profile; отдельный frontend build не создаётся.

### 11.2. Мастер первого подключения

```text
Регистрация подтверждена
  → Создать терминал
  → Получить PIN
  → Скачать последний Agent artifact
  → Установить по инструкции
  → Проверить certificate/IoT online
  → Запустить console или video
```

Показываются четыре readiness-status: Агент, сертификат, IoT/RPC, видео.

### 11.3. Раздел «Лицензии»

- текущий баланс и кнопка пополнения;
- индивидуальная граница цикла;
- `active/grace/blocked` и точное время блокировки;
- прогресс общей бесплатной квоты `console + video`;
- прогноз следующего цикла;
- детализация: terminal, date, minutes, free minutes, rounding, discarded kopecks, amount;
- понятные причины отказа от запуска.

## 12. Хаб superuser

### 12.1. Вкладки

1. **Регистрации** — tenant, user/email, источник, email confirmation, onboarding, первая оплата.
2. **Терминалы** — tenant, terminal/SN, PIN/certificate, provisioning, Agent version/capabilities, first/last online, free/paid.
3. **Сессии и usage** — console/video, lifecycle, duration, reason, user, free/paid, event/session/correlation IDs.
4. **Лицензии и финансы** — cycle, balance, entitlement, charges, ЮKassa/manual payments, reversals, discarded kopecks, reconciliation.
5. **Уведомления и ошибки** — email delivery, provisioning, RPC, media, payment и retry state.

### 12.2. Фильтры MVP

- tenant;
- terminal/SN;
- period;
- user/email;
- event type и status;
- console/video;
- `active/grace/blocked`;
- free/paid usage;
- ЮKassa/manual;
- `provider_payment_id`;
- `session_id`;
- `correlation_id`;
- только ошибки;
- только несверенные записи.

Главный диагностический путь:

```text
registration
→ provisioning
→ PIN/certificate
→ device_online
→ remote session
→ fin_usage_daily
→ ledger transaction
→ payment
```

## 13. Архивирование и срок хранения

### 13.1. Что остаётся online

Не удаляются при оперативной архивации:

- financial ledger и payments;
- billing cycles и balance projections;
- daily/monthly financial aggregates;
- итоговые session rows;
- reconciliation results;
- source hashes и archive manifests.

Финансовая история хранится минимум `3 года` и входит в резервное копирование.

### 13.2. Что архивируется после трёх полных месяцев

- подробные IoT session events;
- RPC transitions;
- presence/heartbeat history;
- l4media technical samples;
- массовые application audit details.

Технические архивы также хранятся минимум `3 года` для полной сверки.

### 13.3. Формат на смонтированном томе

```text
<mounted-volume>/l4desk-archive/<year>/<month>/<project>/<archive_batch_id>/
  data.jsonl.gz
  manifest.json
  checksum.sha256
```

`manifest` содержит schema version, row counts, min/max timestamps, source types и checksum.

Порядок:

1. Выбрать только закрытый месяц старше трёх полных месяцев.
2. Создать общий `archive_batch_id`.
3. Каждый проект экспортирует только собственные данные.
4. Записать временный пакет и выполнить `fsync`/закрытие файла.
5. Рассчитать SHA-256.
6. Повторно прочитать пакет и сверить manifest.
7. Атомарно переименовать временный каталог.
8. Пометить batch как `verified`.
9. Проверить, что consumer cursor прошёл архивную границу.
10. Только после этого удалить массовые горячие детали.

Mounted volume обязан входить в отдельное резервное копирование. Наличие файла на host volume не является backup.

Финансовые ссылки на удаляемые технические детали используют `source_project`, `source_event_id`, `source_events_hash`, `archive_batch_id`, но не обязательный FK.

## 14. Безопасность и аудит

- service-to-service API защищён отдельным credential и network policy;
- tenant/user headers не принимаются от публичного клиента без auth boundary;
- `org_id`/tenant id приводится к числовому типу на границе auth;
- certificate PIN одноразовый, ограниченный по времени и журналируется;
- секреты ЮKassa, email и service tokens только в environment/secrets;
- webhook/polling идемпотентны;
- каждая финансовая и superuser-операция имеет actor, timestamp и correlation;
- проведённые документы не изменяются;
- архивы имеют checksum, ограниченный доступ и backup;
- email verification и payment return URLs защищены от replay/open redirect;
- один terminal принадлежит только одному tenant одновременно.

## 15. Наблюдаемость и контроль готовности

Минимальные метрики:

- registration/email confirmation success/failure;
- provisioning и certificate PIN success/failure;
- device online count;
- active console/video sessions;
- session start latency и stop reasons;
- event feed cursor lag;
- usage worker lag;
- ledger imbalance count — всегда `0`;
- reconciliation mismatch count — всегда `0`;
- YooKassa pending age/webhook/polling failures;
- tenants in grace/blocked;
- archive batch status/checksum failures.

Для всех сквозных операций обязателен `correlation_id`.

## 16. Критерии готовности MVP

1. Новый пользователь подтверждает email и получает tenant/role 5.
2. Создаёт terminal, получает PIN и видит provisioning state.
3. Текущий опубликованный Агент подключается без изменения старого контракта.
4. Console и video работают через единую существующую реализацию и взаимно исключаются.
5. Первый terminal и первые 120 минут в сутки бесплатны.
6. Положительный balance позволяет продолжить после 120 минут по платному тарифу.
7. Terminal-month, daily usage, ЮKassa и manual payment дают объяснимые двойные проводки.
8. Grace работает относительно границы цикла и не даёт дополнительных бесплатных дней.
9. Email-уведомления идемпотентны.
10. Хаб связывает первичный факт, расчёт и проводку.
11. Финансовая сверка и баланс совпадают.
12. Архив создаётся, проверяется и восстанавливается до удаления hot details.
13. Contract/backward-compatibility и end-to-end тесты проходят.
14. Production smoke не нарушает существующих пользователей `MenuBuilder` и Агентов.

## 17. Правила каскада агентских промптов

### 17.1. Изоляция

- Один prompt работает только с одним явно названным проектом/стеком: `iot-rpc-rest-app`, `MenuBuilder`, `ProcessingBackend`, `shared/etranprocessing_db`, `l4media`, `tools` или `l4desk-service`.
- В пределах prompt запрещено просматривать исходный код, изменять файлы, запускать тесты, выполнять commit/push или deploy другого проекта. Единственное разрешённое межпроектное чтение — принятый блок из `l4desk-service/docs/prompts/contract-handoff.md` и перечисленные в нём immutable contract artifacts с проверяемым digest.
- Если одна бизнес-задача требует изменений нескольких проектов, она делится на строго последовательные подпункты с общим номером и индексами `A`, `B`, `C`, например `06A → 06B → 06C`. Каждый подпункт имеет одного владельца и отдельный отчёт.
- Provider-подпункт сначала публикует additive contract и совместимую реализацию в своём проекте. Consumer-подпункт получает только опубликованный artifact и реализует свою сторону без открытия provider repository.
- Сводные решения, cross-project acceptance и реестр версий выполняются отдельным prompt проекта `l4desk-service`. Такой prompt не меняет остальные проекты и использует только их подписанные отчёты/артефакты либо публичные deployed endpoints.
- Агент не расширяет scope без отдельного prompt. Обнаруженная необходимость изменить другой проект фиксируется как blocker и порождает следующий индексированный prompt, а не скрытое дополнительное изменение.
- Существующие unrelated изменения пользователя не откатываются и не включаются в push.
- Один commit, push, deployment и rollback scope всегда относятся только к проекту текущего prompt.

### 17.2. Обязательный жизненный цикл каждого implementation prompt

Каждое будущее тело prompt должно явно требовать:

1. Зафиксировать `scope_project` и проверить, что рабочая область не содержит операций с другими проектами.
2. Прочитать в едином `contract-handoff.md` ровно указанные в prompt блоки `required_handoff_ids` как неизменяемый внешний input и проверить их artifacts/digests, не открывая repository предыдущего агента.
3. Проверить актуальный код и production-compatible baseline только текущего проекта.
4. Разработать только назначенный scope под feature flag/additive contract, где применимо.
5. Написать/обновить только внутренние для текущего проекта unit, integration, provider/consumer contract и backward-compatibility tests.
6. Выполнить lint/type/build/test проверки только текущего проекта. Межпроектная проверка заменяется contract tests против зафиксированных fixtures/schema.
7. Обновить документацию только текущего проекта.
8. Создать внутри текущего проекта отчёт шага с изменениями, версиями контрактов, тестами, migration/deploy/rollback и открытыми рисками.
9. Подготовить дословный candidate-блок для единого `contract-handoff.md`: OpenAPI/JSON Schema/examples, identifiers, errors, compatibility, artifact digests и deployment status.
10. Commit и push выполнять только для текущего проекта, в явно указанную prompt-ветку и только после зелёных проверок.
11. Deploy выполнять только для текущего проекта по его runbook; для проектов внутри `etranprocessing` — только на утверждённый production host `87.242.100.34`.
12. После deploy выполнить только project-local migrations, smoke/contract probes и rollback readiness check.
13. Не отмечать подпункт завершённым до успешного post-deploy отчёта со статусом `ACCEPTED`.

Docs-only prompt `l4desk-service` вместо service deploy публикует и версионирует документ/реестр. Prompt `tools` публикует только принадлежащий ему Agent artifact. Destructive schema activation в contract prompt запрещена.

### 17.3. Строгая последовательность

- Строки реестра выполняются строго сверху вниз, включая буквенные подпункты: `A`, затем `B`, затем `C`.
- Следующий prompt запускается только после статуса `ACCEPTED` в отчёте непосредственно предыдущего.
- Параллельное выполнение шагов запрещено.
- Если provider contract не задеплоен совместимо, consumer prompt не запускается.
- Schema выполняется expand → compatible code → backfill/switch → contract.
- Production activation коммерческой политики выполняется только после E2E acceptance.
- Любой failed test, migration, deploy или smoke блокирует каскад и порождает отдельный corrective prompt.
- Corrective prompt получает суффикс текущего подпункта, например `08A-FIX-01`, и остаётся в том же единственном проекте. Если исправление нужно в другом проекте, создаётся новый следующий подпункт с новым владельцем.

### 17.4. Стандарт handoff

Единственным источником фактически принятых межагентных контрактов является append-only файл:

```text
l4desk-service/docs/prompts/contract-handoff.md
```

Каждый агент до начала работы ищет по точным маркерам каждый `required_handoff_id`, требует ровно один блок со статусом `ACCEPTED`, проверяет, что текущий `prompt_id` указан в `consumers`, и сверяет версии, пути и `SHA-256` immutable artifacts. Отсутствующий, неоднозначный, отозванный, неполный или не адресованный текущему шагу блок приводит к `BLOCKED_CONTRACT`. Восстанавливать контракт по памяти, архитектурному описанию, коду соседнего проекта или deployed endpoint запрещено.

Локальный отчёт шага публикуется только в текущем проекте:

```text
<scope_project>/docs/l4desk/handoffs/<prompt_id>-report.md
```

Runtime-агент не редактирует общий журнал, чтобы не нарушать правило одного проекта. Он включает в свой отчёт готовый к дословной вставке candidate-блок с `handoff_id`, producer/consumer, commit/branch, contract/schema/artifact versions, путями и digest artifacts, feature flags, tests, deploy/smoke, rollback и risks. Контроллер каскада независимо проверяет факты и append-only операцией добавляет блок в общий журнал. Агент `l4desk-service` может добавить собственный блок напрямую, поскольку журнал входит в его scope. Следующий prompt не запускается до фактической фиксации принятого блока в этом файле.

Принятый блок не редактируется. Ошибка оформляется отдельной записью `REVOCATION` и новым versioned handoff с `supersedes`. Полный формат, алгоритм однозначного чтения и bootstrap первого шага определены в `l4desk-service/docs/prompts/contract-handoff.md`; обязательный жизненный цикл — в `l4desk-service/docs/prompts/PROMPT-STANDARD.md`.

## 18. Реестр каскада промптов

Ниже приведены только названия, шаги и назначение. Тела промптов создаются отдельно перед выполнением каждого шага.

| Шаг | Проект/стек | Название промпта | Назначение |
|---:|---|---|---|
| 00A | `tools` | `L4D-00A-TOOLS — Зафиксировать baseline Агента` | Только в `tools` проверить текущий опубликованный Agent/leo4proxy, MQTT/RPC fixtures, version/capabilities, внутренние тесты и artifact delivery; push/publish отчёт и Agent baseline handoff. |
| 00B | `iot-rpc-rest-app` | `L4D-00B-IOT — Зафиксировать baseline device/RPC-контура` | Только в IoT-проекте проверить device registry, MQTT/RabbitMQ, RPC, remote-input, billing alpha, API, тесты и deploy state; push отчёт и IoT baseline handoff. |
| 00C | `ProcessingBackend` | `L4D-00C-PB — Зафиксировать baseline сертификатного контура` | Только в `ProcessingBackend` проверить PIN/CSR/X.509 API, terminal binding, Alembic authority, тесты и deploy state; push отчёт и certificate baseline handoff. |
| 00D | `l4media` | `L4D-00D-MEDIA — Зафиксировать baseline медиаконтура` | Только в `l4media` проверить ingress/Janus/routes, stream lifecycle, health/stop API, тесты и deploy state; push отчёт и media baseline handoff. |
| 00E | `MenuBuilder` | `L4D-00E-MB — Зафиксировать baseline коммерческого и UX-контура` | Только в `MenuBuilder` проверить tenant/users/terminals, текущие console/video use cases, IoT client, billing UI/backend, тесты и deploy state; push отчёт и MenuBuilder baseline handoff. |
| 00F | `shared/etranprocessing_db` | `L4D-00F-SHARED — Зафиксировать baseline общей модели данных` | Только в `shared/etranprocessing_db` проверить модели, constraints, packaging и внутренние проверки; push отчёт и shared-schema baseline handoff. |
| 00G | `l4desk-service` | `L4D-00G-DOCS — Собрать принятый baseline и карту контрактов` | Только в `l4desk-service` принять handoff-артефакты `00A–00F`, сформировать central baseline/version matrix и опубликовать вход каскада без открытия или изменения других repositories. |
| 01A | `tools` | `L4D-01A-TOOLS — Опубликовать Agent Compatibility Contract v1` | Только в `tools` оформить golden vectors существующих topics/method codes/payload, capability matrix и backward-compatibility tests; push/publish Agent contract artifact и отчёт. |
| 01B | `iot-rpc-rest-app` | `L4D-01B-IOT — Реализовать provider совместимости Agent Contract v1` | Только в IoT-проекте принять artifact `01A`, реализовать/закрепить adapter и provider contract tests без изменения Агента; push/deploy совместимую реализацию и IoT handoff. |
| 01C | `l4desk-service` | `L4D-01C-DOCS — Зарегистрировать принятую пару Agent/IoT контрактов` | Только в `l4desk-service` сверить отчёты `01A–01B`, зафиксировать accepted versions/fixtures и опубликовать immutable contract reference для следующих шагов. |
| 02 | `iot-rpc-rest-app` | `L4D-02-IOT — Реализовать durable session facts и event feed` | Только в IoT-проекте разработать идемпотентные device/session events, cursor feed и reconciliation API; внутренние/contract tests, push/deploy и OpenAPI/events handoff. |
| 03 | `MenuBuilder` | `L4D-03-MB — Подключить IoT Contract Consumer v1` | Только в `MenuBuilder` принять artifact `02`, реализовать versioned client, cursor consumer и idempotency без финансовой политики; внутренние/consumer tests, push/deploy и compatibility handoff. |
| 04A | `shared/etranprocessing_db` | `L4D-04A-SHARED — Добавить declarative expand-модели L4Desk и fin_*` | Только в shared-проекте добавить тонкие SQLAlchemy-модели, constraints/index metadata и package tests; push/publish новую совместимую версию и schema-model handoff. |
| 04B | `ProcessingBackend` | `L4D-04B-PB — Добавить Alembic expand-миграцию L4Desk и fin_*` | Только в `ProcessingBackend` принять artifact `04A`, создать недеструктивную миграцию единственной Alembic-цепочки, проверить upgrade/downgrade; push/deploy migration и schema-revision handoff. |
| 04C | `MenuBuilder` | `L4D-04C-MB — Подключить совместимую expand-схему L4Desk` | Только в `MenuBuilder` принять package/schema artifacts `04A–04B`, обновить свою зависимость и project-local schema compatibility tests; push/deploy тёмную интеграцию и consumer handoff. |
| 05 | `MenuBuilder` | `L4D-05-MB — Реализовать саморегистрацию и email confirmation` | Только в `MenuBuilder` разработать public registration, atomic user/tenant/role 5 creation, timezone и audit; внутренние тесты, push/deploy под feature flag и onboarding handoff. |
| 06A | `ProcessingBackend` | `L4D-06A-PB — Опубликовать идемпотентный Certificate PIN Contract` | Только в `ProcessingBackend` закрепить PIN/CSR/certificate API, idempotency, terminal identifiers и provider tests; push/deploy additive contract и certificate handoff. |
| 06B | `iot-rpc-rest-app` | `L4D-06B-IOT — Реализовать идемпотентный device provisioning contract` | Только в IoT-проекте реализовать provisioning endpoint/state/events с устойчивыми identifiers; внутренние/contract tests, push/deploy и provisioning handoff. |
| 06C | `MenuBuilder` | `L4D-06C-MB — Реализовать terminal onboarding по принятым контрактам` | Только в `MenuBuilder` принять artifacts `06A–06B`, связать terminal record, IoT provisioning, certificate PIN и readiness states; тесты, push/deploy и terminal-flow handoff. |
| 07 | `iot-rpc-rest-app` | `L4D-07-IOT — Реализовать единый session lock и graceful stop` | Только в IoT-проекте обеспечить взаимное исключение console/video, lifecycle, command-aware console stop и совместимость Agent Contract v1; тесты, push/deploy и session-control handoff. |
| 08A | `l4media` | `L4D-08A-MEDIA — Укрепить on-demand media lifecycle contract` | Только в `l4media` реализовать идемпотентные route/mountpoint start/health/stop, session identifiers и cleanup/timeout; внутренние тесты, push/deploy и media-control handoff. |
| 08B | `MenuBuilder` | `L4D-08B-MB — Унифицировать console/video orchestration` | Только в `MenuBuilder` принять artifacts `07` и `08A`, направить старый и новый UX в один use case и добавить tenant/session policy seam; тесты, push/deploy и frontend API handoff. |
| 09 | `MenuBuilder` | `L4D-09-MB — Реализовать финансовое ядро двойной записи` | Только в `MenuBuilder` реализовать `fin_accounts`, ledger, balance projection, immutable corrections, whole-ruble posting и reconciliation invariants; тесты, push/deploy тёмной схемы и financial handoff. |
| 10 | `MenuBuilder` | `L4D-10-MB — Реализовать тарифы, billing cycles и metering` | Только в `MenuBuilder` реализовать free terminal, terminal-month по IoT events, daily pooled usage, timezone split, rounding и tariffs; тесты, push/deploy и usage-formula handoff. |
| 11 | `MenuBuilder` | `L4D-11-MB — Реализовать ЮKassa и ручные оплаты` | Только в `MenuBuilder` реализовать top-up, webhook/polling, receipt snapshot и immutable manual payment/storno; тесты, push/deploy и payment handoff. |
| 12 | `MenuBuilder` | `L4D-12-MB — Реализовать entitlement, grace и уведомления` | Только в `MenuBuilder` реализовать first-payment gate, cycle-bound grace, `active/grace/blocked`, periodic stop requests и email `-7/-3/-1/grace/blocked`; тесты, push/deploy и entitlement handoff. |
| 13 | `MenuBuilder` | `L4D-13-MB — Реализовать frontend profile и onboarding UX` | Только в `MenuBuilder` добавить в одну SPA пять разделов, мастер, readiness, единые console/video screens, Licenses UX и MCP waitlist; build/tests, push/deploy под feature flag и UX handoff. |
| 14 | `MenuBuilder` | `L4D-14-MB — Реализовать Хаб и финансовую сверку` | Только в `MenuBuilder` добавить вкладки/фильтры Хаба, correlation drill-down, unmatched filters, manual payment UI и reconciliation runs; тесты, push/deploy и hub/reconciliation handoff. |
| 15A | `l4desk-service` | `L4D-15A-DOCS — Опубликовать общий Archive Manifest Contract` | Только в `l4desk-service` определить `archive_batch_id`, JSONL/manifest/checksum, cursor guards, retention и acceptance fixtures; опубликовать docs contract без изменения runtime-проектов. |
| 15B | `iot-rpc-rest-app` | `L4D-15B-IOT — Реализовать архив IoT/RPC подробностей` | Только в IoT-проекте принять artifact `15A`, реализовать monthly archive, verification, cursor guard и purge verified details; restore tests, push/deploy и IoT archive handoff. |
| 15C | `l4media` | `L4D-15C-MEDIA — Реализовать архив media technical details` | Только в `l4media` принять artifact `15A`, реализовать пакетирование media samples/events, checksum verification и purge verified details; restore tests, push/deploy и media archive handoff. |
| 16 | `MenuBuilder` | `L4D-16-MB — Реализовать финансовые archive manifests и retention` | Только в `MenuBuilder` принять artifacts `15A–15C`, связать archive batches/source hashes, сохранить ядро/агрегаты online и обеспечить трёхлетний retention; тесты, push/deploy и archive-coordination handoff. |
| 17A | `tools` | `L4D-17A-TOOLS — Провести приёмку опубликованного Агента` | Только в `tools` проверить текущий release против Agent Contract v1 и сценариев console/video без публикации несовместимого протокола; push/publish acceptance report и artifact evidence. |
| 17B | `ProcessingBackend` | `L4D-17B-PB — Провести приёмку certificate/PIN-контура` | Только в `ProcessingBackend` выполнить project-local production smoke и provider contract probes для PIN/CSR/certificate; push отчёт и certificate acceptance handoff. |
| 17C | `iot-rpc-rest-app` | `L4D-17C-IOT — Провести приёмку device/RPC-контура` | Только в IoT-проекте выполнить production smoke для provisioning, Agent compatibility, session lock, event feed, graceful stop и archive; push отчёт и IoT acceptance handoff. |
| 17D | `l4media` | `L4D-17D-MEDIA — Провести приёмку медиаконтура` | Только в `l4media` выполнить production smoke start/health/stop, cleanup и archive restore; push отчёт и media acceptance handoff. |
| 17E | `MenuBuilder` | `L4D-17E-MB — Провести приёмку коммерческого контура` | Только в `MenuBuilder` выполнить project-local/consumer acceptance регистрации, onboarding, usage, payment, ledger, grace, UI и Хаба по зафиксированным fixtures/endpoints; push отчёт и commercial acceptance handoff. |
| 17F | `l4desk-service` | `L4D-17F-DOCS — Провести black-box E2E и оформить решение о приёмке` | Только в `l4desk-service` использовать deployed public/internal test interfaces и отчёты `17A–17E` для сценария registration → terminal/PIN → Agent → console/video → billing → archive; опубликовать `ACCEPTED` либо перечень изолированных corrective prompts. |
| 18A | `shared/etranprocessing_db` | `L4D-18A-SHARED — Зафиксировать production-версию shared package` | Только в shared-проекте проверить и опубликовать финальную совместимую package version, provenance и rollback instructions; push release report и package handoff. |
| 18B | `ProcessingBackend` | `L4D-18B-PB — Выполнить финальный production rollout ProcessingBackend` | Только в `ProcessingBackend` принять artifact `18A`, применить утверждённую migration/release, выполнить smoke и rollback readiness; push deployment report и provider handoff. |
| 18C | `iot-rpc-rest-app` | `L4D-18C-IOT — Выполнить финальный production rollout IoT` | Только в IoT-проекте активировать совместимые provider-функции, проверить старых Агентов, event feed и rollback; push deployment report и IoT handoff. |
| 18D | `l4media` | `L4D-18D-MEDIA — Выполнить финальный production rollout l4media` | Только в `l4media` активировать media lifecycle/archive изменения, выполнить stream smoke и rollback check; push deployment report и media handoff. |
| 18E | `MenuBuilder` | `L4D-18E-MB — Активировать production-функции L4Desk` | Только в `MenuBuilder` принять provider deployment handoffs `18B–18D`, выполнить deploy и последовательно включить L4Desk feature flags; проверить старых пользователей, финансы, UI и rollback, затем push deployment report. |
| 18F | `l4desk-service` | `L4D-18F-DOCS — Выпустить итоговый реестр версий и эксплуатационный отчёт` | Только в `l4desk-service` собрать принятые release reports, зафиксировать deployed versions/contracts/migrations/flags/rollback и опубликовать финальный operations handoff без изменения runtime-проектов. |

## 19. Решение о старте разработки

Разработка начинается строго с `00A` и идёт по строкам реестра без пропусков и параллельного запуска. Этап `00` формирует изолированные baseline-отчёты и только затем их документальную консолидацию. Этапы `01A–01C` фиксируют Agent compatibility до развития IoT contract. Финансовая схема `04A–04C` не начинается до принятия устойчивых identifiers и session/device facts `02–03`. Terminal onboarding разделён на независимые provider/consumer подпункты `06A–06C`. Единая orchestration MenuBuilder `08B` не начинается до готовности IoT и l4media provider contracts `07–08A`.

UI нельзя активировать раньше готовности entitlement и финансового ядра. Архивация выполняется после стабилизации первичных событий, но до изолированной приёмки каждого проекта и документального black-box E2E. Финальная production-активация выполняется только по подпунктам `18A–18F` после `ACCEPTED` в `17F`.

Любое изменение контракта в ходе каскада возвращает процесс к соответствующему provider-проекту через отдельный corrective prompt и новый handoff. Ни один агент не исправляет соседний проект самостоятельно; молчаливое расхождение контрактов запрещено.
