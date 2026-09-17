# H-L4D-00B-IOT-v1 — Отчёт о фиксации baseline device/RPC-контура (`iot-rpc-rest-app`)

```yaml
handoff_id: H-L4D-00B-IOT-v1
prompt_id: L4D-00B-IOT
previous_handoff_ids:
  - H-L4D-00A-TOOLS-v1
next_prompt_id: L4D-00C-PB
target_repository: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
git_commit: 2488395
git_branch: l4desk/l4d-00b-iot
app_version: 0.2.1
created_at: 2026-09-17T17:45:00Z
architecture_sections: [3, 4, 5, 11, 12, 15, 17]
status: VERIFIED
```

---

## 1. Executive Summary

В рамках выполнения промпта `L4D-00B-IOT` зафиксирован production-compatible baseline сервиса `iot-rpc-rest-app` (`app1`), обеспечивающего приём телеметрии, маршрутизацию RPC-задач оборудования через RabbitMQ/MQTT, сессии удалённого управления (`remote_input`), интерактивную диагностику и предварительный учёт ресурсов (alpha billing).

Ключевые результаты шага:
1. **Contract Gate**: проверен входной handoff `H-L4D-00A-TOOLS-v1` и подтверждены контрольные суммы SHA-256 всех 6 входных golden fixtures.
2. **Инвентаризация контура**: зафиксированы схемы моделей данных, топики и очереди RabbitMQ/MQTT, RPC-механизм (`tsk/req/rsp/res/cmt/eva`), жизненный цикл lease/presence/pending, REST/WS API и фоновые воркеры.
3. **Совместимость с Golden Fixtures**: создан специализированный тестовый набор `app-service/tests/core/test_l4d_00b_baseline_fixtures.py` (12 тестов), подтверждающий совместимость и детально фиксирующий контрактные различия и проекции типов. Все 333 теста репозитория проходят успешно.
4. **Alpha Billing**: архитектурно изолирован и описан как эвристический счётчик потребления/активности, не являющийся финансовым источником истины.
5. **Анализ пробелов (Gaps)**: задокументированы 5 критических зон развития (durable event feed, provisioning/revocation, distributed mutual exclusion, graceful stop/drain, archival readiness).
6. **Production Probes**: выполнены read-only зонды целевого хоста (`etranprocessing` / `87.242.100.34`), подтвердившие статус контейнера `app1` (Up 3 days, commit `2488395`).

---

## 2. Input Contract Gate (H-L4D-00A-TOOLS-v1)

Все входные артефакты из каталога `D:\repo\platerra\Public\etranprocessing\tools\docs\l4desk\fixtures\` сверены по содержимому и контрольным суммам SHA-256. Расхождений не обнаружено.

| Артефакт / Файл | SHA-256 Digest | Статус верификации |
|---|---|---|
| `L4D-00A-TOOLS-report.md` | `84540e42b622f5222b854afcb68f6c86c992d7506b60d8e212d01d5c46a16950` | Проверен |
| `rpc_7001_exec.json` | `4007bbf50a5280abfaf747f7c8a28344a4f61e2ac4f2a60a0c80aec5018578bf` | Совпадает |
| `rpc_7000_stream_control.json` | `dba8ff769f12239765c2317b96a8fa2e8f60cdccbc0de00113b9d4ce7e54b9b8` | Совпадает |
| `baseline_capabilities.json` | `375412eaa61e31e72b2ea5f002862a1d1f02becdd4626a71af31d9400df560cb` | Совпадает |
| `rpc_7002_cancel.json` | `2965f6e24d8c88b82b08b6dec892c271750a91f1a89f82cc8eb1b19fa8779d22` | Совпадает |
| `mqtt_presence_lifecycle.json` | `f6a59507fc9cbed6c2f4bf707360affedb6344cac01b7f49b12d8cf3cff08e28` | Совпадает |
| `l4rtp_wire_protocol.json` | `eb8500895d8f679cd0baa59e150c8b94e8a78d8eca5b7c9f086654c066c35277` | Совпадает |

---

## 3. Архитектурная инвентаризация (Architecture Sections)

### §3. Общая схема взаимодействия компонентов
- **Ядро сервиса**: FastAPI `>= 0.135` + FastStream `0.6.6` (RabbitMQ broker integration) на Python `3.14-slim`.
- **База данных**: PostgreSQL через SQLAlchemy 2.0 (asyncio + `asyncpg`). Пул соединений: `pool_size=50`, `max_overflow=10`.
- **Брокер сообщений**: RabbitMQ 4 с плагинами `rabbitmq_management`, `rabbitmq_mqtt`, `rabbitmq_event_exchange`.
- **Внешние потребители/интеграции**:
  - `MenuBuilder` (BFF/UI): вызывает REST/WS эндпоинты `/api/internal/v1/remote-input` для инициализации lease, запуска видеопотока и передачи действий оператора.
  - Терминалы (`l4desk` / `leo4proxy`): подключаются по MQTT 5 с mTLS к портам `8883` / `4443` / `8443`.
  - Фоновые воркеры: FastStream subscribers для входящих очередей, APScheduler для периодических джоб (TTL, реконсиляция подключений, биллинг).

### §4. Брокер сообщений, очереди и топики (RabbitMQ / MQTT 5)
Взаимодействие разделено на обменники `amq.topic`, `amq.direct` и `amq.rabbitmq.event`:

1. **Топики уровня устройства (`amq.topic`)**:
   - `dev.<SN>.req` → очередь `req`: запрос следующей RPC-задачи терминалом (RPC poll).
   - `dev.<SN>.ack` → очередь `ack`: подтверждение приёма задачи устройством (`TaskStatus.PENDING`).
   - `dev.<SN>.res` → очередь `res`: результат исполнения задачи (`TaskStatus.DONE`), триггерит отправку в очередь вебхуков и `srv.<SN>.cmt`.
   - `dev.<SN>.evt` → очередь `evt`: асинхронные события телеметрии устройства.
   - `dev.<SN>.out` → очередь `out` (non-durable, TTL 600 с): потоковый вывод диагностики (stdout/stderr).
   - `dev.<SN>.ctl` → очередь `ctl` (non-durable, TTL 15 с): интерактивные ответы (`ack`, `nack`, `presence`, `stream_event`) от `l4desk`.
   - `dev.<SN>.app` → очередь `app` (durable): presence и LWT основного приложения киоска (`app_online` / `app_offline`).
   - `dev.<SN>.svc` → очередь `svc` (durable): presence и LWT сервисной службы (`svc_online` / `svc_offline`).

2. **Топики уровня сервера (`amq.topic`)**:
   - `srv.<SN>.tsk`: анонс появления новой задачи (trigger notify).
   - `srv.<SN>.rsp`: доставка тела задачи и параметров RPC (RPC response на `req`).
   - `srv.<SN>.cmt`: серверный коммит завершения задачи (после сохранения результата).
   - `srv.<SN>.eva`: подтверждение приёма серверного события (`dev_event_id`, `event_type_code`).
   - `srv.<SN>.ctl`: прямые команды интерактивного управления (`pointer_move`, `mouse_click`, `key_event`, `shortcut_action`, `inventory_get`, `stream_start`, `stream_stop`, `lease_renew`). Публикуются **без retain**, QoS 1.

3. **Системные очереди (`amq.direct` и `amq.rabbitmq.event`)**:
   - `iot.device.connection.events`: события `connection.created`, `connection.closed` из `amq.rabbitmq.event`.
   - `core_jobs`: очередь задач планировщика (TTL decrement `act_ttl`).
   - `rmq_api_client_action`: асинхронные команды управления учётными записями RabbitMQ Admin API.
   - `webhook_action`: очередь диспетчеризации HTTP вебхуков.
   - `billing_counter_action`: очередь событий потребления ресурсов (alpha billing).

### §5. Аутентификация, безопасность и изоляция
- **mTLS на транспорте MQTT**: каждый терминал авторизуется по клиентскому сертификату, Common Name (CN) сертификата является доверенным `SN` оборудования.
- **REST / WebSockets авторизация**:
  - Публичный API (`/api/v1/`): требует заголовок `x-api-key`. Автоматическая привязка к организации (`org_id`).
  - Внутренний API (`/api/internal/v1/`): скрыт из публичной OpenAPI-схемы (`include_in_schema=False`), предназначен для доверенных межсервисных вызовов (MenuBuilder BFF). Привязка `x-api-key` проверяется с валидацией принадлежности целевого устройства (`device.org_id == auth_org_id`).
- **Блокировка конкурентной синхронизации**: при старте нескольких инстансов используется PostgreSQL advisory lock (`SELECT pg_try_advisory_xact_lock(2026080501)`), предотвращающий thundering herd при реконсиляции ACL в RabbitMQ.

### §11. Жизненный цикл сессий и Lease Management
- **Реестры состояния в памяти (`core/remote_input/`)**:
  - `LeaseRegistry`: выдача и продление временных аренд с монопольным доступом (`asyncio.Lock`).
    - Поддерживаемые scopes: `console`, `view`, `stream`, `input`.
    - Правило монополии: только один активный держатель lease на терминал. При отзыве lease генерируется принудительная остановка стрима (`stream_stop`) и закрытие связанных сессий диагностики.
    - Автоматическая очистка: фоновый цикл `_remote_input_cleanup_loop` проверяет истечение lease каждую секунду (`lease_ttl_sec=60`, `lease_keepalive_sec=15`).
  - `PresenceRegistry`: кэш последнего статуса `l4desk` (screen geometry, displays inventory, cameras, active stream). Пометка `stale` через `presence_stale_sec=90`.
  - `PendingCommandRegistry`: реестр ожидающих терминального ACK/NACK команд с лимитом `pending_max_per_lease=32`, таймаутом `click_ack_timeout_ms=5000` и корреляцией `command_id <-> lease_id`.

### §12. Команды удалённого управления и RPC-контур
- **RPC 7000–7099 (Диагностика и управление)**:
  - `7000 (CMD_DIAG_STREAM_CONTROL)`: управление стримом (`start`, `stop`), инвентаризация и действия ввода через стандартную очередь RPC `srv.<SN>.rsp` -> `dev.<SN>.res`.
  - `7001 (CMD_DIAG_EXEC)`: запуск процесса диагностики (`cmd`, `powershell`). Вывод стримится фрагментами в `dev.<SN>.out` (`DeviceOutputEnvelope`).
  - `7002 (CMD_DIAG_CANCEL)`: отмена запущенной задачи диагностики по `session_id`.
- **Низколатентный канал управления (`srv.<SN>.ctl` / `dev.<SN>.ctl`)**:
  - Позволяет передавать команды ввода (`mouse_click`, `shortcut_action`, `pointer_move`) напрямую без задержек опроса задач (`req`).
  - Гарантии: `QoS 1`, команды не ретейнятся, дедупликация по `command_id`.
  - Доверенные поля: `SN`, `lease_id`, `command_id`, временные метки формируются исключительно сервером. Попытка передачи произвольных идентификаторов клиентом пресекается.

### §15. Учёт ресурсов и Alpha Billing
- **Модель расчёта**:
  $$\text{consumption} = P_1 + P_2 + P_3 + P_4$$
  - $P_1 = \text{active\_devices} \times k_1$ (число активных устройств за период, дефолт $k_1 = 10000.0$)
  - $P_2 = \text{api\_requests} \times k_2$ (число вызовов REST API, перехваченных middleware, дефолт $k_2 = 1.0$)
  - $P_3 = \text{evt\_messages} \times k_3$ (число входящих событий телеметрии `dev.*.evt`, дефолт $k_3 = 1.0$)
  - $P_4 = \text{res\_payload\_blocks} \times k_4$ (объём результатов RPC блоками по 2048 байт из `dev.*.res`, дефолт $k_4 = 1.0$)
- **Периодичность**: джоба `_billing_monthly_job` запускается в 00:15 1-го числа месяца и рассчитывает агрегированные показатели за прошлый календарный месяц в таблицу `billing_calculation`.
- **Финансовое разграничение**: данная подсистема является сугубо инженерным монитором потребления вычислительных и сетевых ресурсов платформы. Она **не** содержит фискальных гарантий, проводок, защиты от повторного списания при ретраях очереди, интеграции с платёжными шлюзами и бухгалтерского леджера. Использование допускается только в качестве технического индикатора утилизации.

### §17. Развёртывание, надёжность и масштабирование
- **Инвариант единого воркера (Single Worker Invariant)**:
  В `create_api_app.py` зафиксировано критическое системное предупреждение:
  ```
  Memory-only state (remote_input, diagnostics) requires a single gunicorn worker (WEB_CONCURRENCY=1).
  Current workers=... Running with >1 workers will cause lease/pending/presence state desynchronization across workers!
  ```
  В текущей версии состояние lease, pending команд и активных сессий хранится в памяти процесса. Масштабирование на несколько процессов gunicorn или несколько контейнеров невозможно без выноса состояния в Redis/распределённый кэш.
- **Миграции БД**: автоматическое применение при старте контейнера в `prestart.sh` (`alembic upgrade head`). В репозитории зафиксированы 3 актуальные миграции (`2026_08_26_0001`, `2026_08_27_0002`, `2026_08_30_0003`).

---

## 4. Результаты тестов и матрица совместимости с Golden Fixtures

В репозиторий добавлен контрактный тест `app-service/tests/core/test_l4d_00b_baseline_fixtures.py`, валидирующий соответствие принятым фикстурам.

### Результаты прогона тестового набора
- **Общее число тестов**: 333 passed, 0 failed, 3 warnings (Pydantic V2 deprecation, FastStream router alias).
- **Специализированные контрактные тесты**: 12 passed.

### Матрица совместимости и проекция типов

| Фикстура | Метод / Сущность | Спецификация Fixture | Реализация Provider (`iot-rpc-rest-app`) | Статус и правила проекции |
|---|---|---|---|---|
| `rpc_7001_exec.json` | 7001 `CMD_DIAG_EXEC` | `session_id` — произвольная строка (`sess-exec-9001`); chunks без полей `kind`, `stream` | `session_id` строго `UUID`; `DeviceOutputEnvelope` требует `kind: OutputKind` и `stream: str` | **Совместимо через проекцию**: строковый ID мапится в детерминированный/сгенерированный UUID; фреймы выводятся с `kind="stdout"`/`"result"`. |
| `rpc_7000_stream_control.json` | 7000 `CMD_DIAG_STREAM_CONTROL` | Команды содержат строковый `command_id` (`inv_001`, `str_001`), координаты `x_norm`, `y_norm` (float 0..1) | Серверные команды (`core.remote_input.schemas`) требуют `UUID` command_id, `lease_id`, `sn`, целые координаты `0..65535` | **Совместимо через проекцию**: `x_int = int(x_norm * 65535)`, сервер генерирует UUID и привязывает активный `lease_id`. |
| `baseline_capabilities.json` | Capabilities Matrix | Версия l4tools 1.7.7, методы 7000, 7001, 7002, кодек h264, порты 5004/5005 | Модели `core.diagnostics` и `core.remote_input` полностью поддерживают заявленные методы | **Полная совместимость**: структура методов и кодеков совпадает. |
| `rpc_7002_cancel.json` | 7002 `CMD_DIAG_CANCEL` | `target_session_id`, `reason` | `DiagCancelPayload(session_id=..., reason=...)` | **Полная совместимость**: мапинг по `session_id`. |
| `mqtt_presence_lifecycle.json` | Presence / LWT | `dev/{SN}/app` (`app_online`/`app_offline`), `dev/{SN}/svc` (`svc_online`/`svc_offline`), retain=true, QoS 1 | Очереди `q_app` (`dev.*.app`) и `q_svc` (`dev.*.svc`) в `core/topologys/fs_queues.py` | **Полная совместимость**: события обновляют поля `is_app_connected` и `is_svc_connected` в БД. |
| `l4rtp_wire_protocol.json` | L4RTP Wire Protocol | Заголовок `L4RT`, версия 0x01, длина SN (uint16), ASCII SN; каналы 0x01 (RTP) и 0x02 (RTCP) | Байтовый стрим L4RTP терминируется на ingress-прокси (Nginx/go2rtc, порт 8443) и не обрабатывается в Python runtime | **Совместимо по границе архитектуры**: app1 отвечает только за сигнализацию (7000), медиа-трафик мультиплексируется на сетевом уровне. |

---

## 5. Deployment Evidence (Production Probes)

В соответствии с регламентом `docs/manual-app1-deploy-runbook.md` выполнены безопасные read-only зонды целевого окружения:

- **Целевой хост**: `etranprocessing` (`user1@87.242.100.34`, ключ `d:\.ssh\id_ed25519`).
- **Путь оркестратора Compose**: `/home/user1/compose.yaml`.
- **Каталог репозитория**: `/home/user1/iot-rpc-rest-app`.
- **Статус контейнера `app1`**:
  ```text
  NAME      IMAGE        COMMAND                  SERVICE   CREATED      STATUS      PORTS
  app1      user1-app1   "./prestart.sh ./app…"   app1      3 days ago   Up 3 days   
  ```
- **Активный коммит на сервере**: `2488395` (`feat(remote-input): implement Step 2A contract for safe quick actions`).
- **Сверка чистоты рабочего дерева на сервере**: `git status --short` показывает отсутствие несохранённых правок в коде (`?? logs/`).

---

## 6. Реестр пробелов и технического долга (Gaps Analysis)

1. **Durable Event IDs / Feed**:
   - События оборудования (`dev_event_id`) генерируются на стороне киоска, но не все устройства гарантируют уникальный монотонный ID.
   - Отсутствует персистентный курсорный стрим событий (Transactional Outbox / Event Sourcing log) для гарантированного replay внешними потребителями.
   - При сбоях отправки вебхуков после 3 попыток уведомление отбрасывается без сохранения в dead-letter replay очередь.

2. **Provisioning & Certificate Revocation**:
   - Генерация сертификатов и токенов киосков привязана к локальным вспомогательным скриптам и internal API.
   - Отсутствует протокол автоматической ротации (ACME/EST/CMPv2) при истечении срока действия сертификатов на киосках.
   - Механизм RabbitMQ definitions sync динамически закрывает доступ заблокированным устройствам, но CRL/OCSP на уровне брокера в реальном времени не валидируется.

3. **Mutual Exclusion & Distributed Locking**:
   - Реестр `LeaseRegistry` и pending-команды хранятся исключительно в оперативной памяти инстанса Python.
   - Сервис жестко ограничен `WEB_CONCURRENCY=1`. При горизонтальном масштабировании неизбежен рассинхрон прав на управление киосками.
   - Требуется переход на распределённые блокировки и хранилище сессий (Redis Redlock / PostgreSQL row-level lease locks).

4. **Graceful Stop & Connection Draining**:
   - При выключении приложения (`SIGTERM`/`SIGINT`) WebSocket-соединения операторов закрываются без отправки структурированного close frame с предупреждением.
   - Зависшие pending-команды не отменяются на терминалах принудительным NACK.
   - Активный видеопоток ffmpeg на терминале продолжает вещание до истечения локального lease TTL при аварийной остановке сервера.

5. **Archival Readiness & Partitioning**:
   - Таблицы `device_events`, `device_tasks`, `device_task_results`, `billing_counters` растут монотонно без секционирования (partitioning) по времени.
   - Отсутствуют встроенные политики ротации и архивации в холодное хранилище (S3/ClickHouse), что грозит деградацией B-tree индексов при масштабировании парка устройств.

---

## 7. Sequence Gate и передача контекста в `L4D-00C-PB`

- **Статус шага `L4D-00B-IOT`**: ПОЛНОСТЬЮ ЗАВЕРШЕН.
- **Выходной идентификатор**: `H-L4D-00B-IOT-v1`.
- **Следующий шаг в цепочке**: `L4D-00C-PB` (`processing-backend`).
- **Критерий готовности к передаче**:
  - Baseline сервиса `iot-rpc-rest-app` зафиксирован на коммите `2488395` в ветке `l4desk/l4d-00b-iot`.
  - Все 6 golden fixtures проверены тестами и подтверждены контрольными суммами.
  - Топология RabbitMQ и топики `srv.<SN>.{tsk,rsp,cmt,eva,ctl}` / `dev.<SN>.{req,ack,res,evt,out,ctl,app,svc}` верифицированы.
  - Все 333 теста проходят успешно, форматирование соответствует стандарту black/pep8.
  - Агент следующего шага (`L4D-00C-PB`) может опираться на `H-L4D-00B-IOT-v1` как на неизменяемый baseline контура IoT.
