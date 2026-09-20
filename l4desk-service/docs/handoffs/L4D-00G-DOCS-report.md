# L4D-00G-DOCS — Центральный отчёт baseline и карта контрактов L4Desk

**Дата:** 2026-09-17  
**Промпт:** `L4D-00G-DOCS`  
**Пакет / Scope:** `l4desk-service` (`D:\repo\platerra\Public\etranprocessing\l4desk-service`)  
**Ветка:** `l4desk/l4d-00g-docs`  
**Статус:** `ACCEPTED`  
**Входные handoffs (Contract Gate):** `[H-L4D-00A-TOOLS-v1, H-L4D-00B-IOT-v1, H-L4D-00C-PB-v1, H-L4D-00D-MEDIA-v1, H-L4D-00E-MB-v1, H-L4D-00F-SHARED-v1]`  
**Выходной handoff:** `H-L4D-00G-DOCS-v1`  
**Следующий промпт (consumer):** `L4D-01A-TOOLS`  
**Разделы архитектуры:** 1, 3, 4, 5, 11, 12, 17, 18, 19  

---

## 1. Резюме выполнения

В рамках шага `L4D-00G-DOCS` выполнена централизованная консолидация и нормативная фиксация всех шести базовых контрактов этапа `00` (`00A–00F`) проекта L4Desk:

1. **Contract Gate & Digest Verification:** Все 6 входных baseline handoff-блоков успешно прочитаны из единого журнала `contract-handoff.md`. Контрольные суммы (SHA-256) опубликованных артефактов и отчётов проверены побайтово и на 100% совпали с эталонными записями.
2. **Анализ согласованности контрактов:** Проведено взаимное сопоставление идентификаторов, версий, границ владения данными и выявленных разрывов (gaps). Ни одного неразрешимого конфликта не обнаружено (`BLOCKED_CONTRACT: NONE`).
3. **Центральная матрица версий (Central Version Matrix):** Зафиксированы фактические production-compatible версии всех 6 компонентов экосистемы.
4. **Сквозная карта Provider / Consumer контрактов:** Построена детальная схема информационных потоков и контрактных интерфейсов между всеми подсистемами.
5. **Нормативное разделение статусов:** В строгом соответствии с архитектурным принципом «не переносить непроверенные утверждения в статус реализованных» проведена чёткая граница между тем, что **фактически реализовано и проверено в baseline** (`IMPLEMENTED & VERIFIED`), и тем, что является **целевой архитектурой последующих этапов** (`TARGET ARCHITECTURE / SCHEDULED`).
6. **Решения этапа 01:** Сформирован исчерпывающий перечень нормативных решений, которые обязан зафиксировать этап `01` (`01A–01C`), начиная с потребителя `L4D-01A-TOOLS`.
7. **Изоляция и границы изменений:** В ходе выполнения шага не открывались и не модифицировались исходные коды соседних runtime-проектов (`tools`, `iot-rpc-rest-app`, `ProcessingBackend`, `l4media`, `MenuBuilder`, `shared`). Все изменения строго ограничены проектом документации и управления каскадом `l4desk-service`.

---

## 2. Contract Gate и верификация шести входных handoff

В соответствии с разделом 1 `contract-handoff.md`, каждый входной handoff-блок проверен на наличие точных маркеров, статуса `ACCEPTED`, непротиворечивости метаданных, наличия `L4D-00G-DOCS` в списке `consumers` и совпадения хешей артефактов.

### 2.1. Сводная таблица верификации входных контрактов

| Handoff ID | Проект (Producer) | Промпт | Версия контракта | Статус | Среда развертывания | Коммит продюсера | Артефакты (кол-во) | Результат Gate |
|---|---|---|---|---|---|---|:---:|:---:|
| `H-L4D-00A-TOOLS-v1` | `tools` | `L4D-00A-TOOLS` | `1.7.7` | `ACCEPTED` | `artifact-registry` | `cff9ddfb` | 7 | **PASSED** |
| `H-L4D-00B-IOT-v1` | `iot-rpc-rest-app` | `L4D-00B-IOT` | `0.2.1` | `ACCEPTED` | `production` | `de431c15` | 2 | **PASSED** |
| `H-L4D-00C-PB-v1` | `ProcessingBackend` | `L4D-00C-PB` | `1.0.0` | `ACCEPTED` | `production` | `3cec1784` | 1 | **PASSED** |
| `H-L4D-00D-MEDIA-v1` | `l4media` | `L4D-00D-MEDIA` | `1.0.0` | `ACCEPTED` | `production` | `47c9b378` | 1 | **PASSED** |
| `H-L4D-00E-MB-v1` | `MenuBuilder` | `L4D-00E-MB` | `0.1.0` | `ACCEPTED` | `production` | `dabccacf` | 3 | **PASSED** |
| `H-L4D-00F-SHARED-v1` | `shared/etranprocessing_db` | `L4D-00F-SHARED` | `0.1.0` | `ACCEPTED` | `local_package` | `97094aed` | 1 | **PASSED** |

### 2.2. Побайтовая верификация артефактов и контрольных сумм SHA-256

#### 1. H-L4D-00A-TOOLS-v1 (tools / Агент)
- `tools/docs/l4desk/fixtures/rpc_7000_stream_control.json`: `dba8ff769f12239765c2317b96a8fa2e8f60cdccbc0de00113b9d4ce7e54b9b8` — **СОВПАДАЕТ**
- `tools/docs/l4desk/fixtures/rpc_7001_exec.json`: `4007bbf50a5280abfaf747f7c8a28344a4f61e2ac4f2a60a0c80aec5018578bf` — **СОВПАДАЕТ**
- `tools/docs/l4desk/fixtures/rpc_7002_cancel.json`: `2965f6e24d8c88b82b08b6dec892c271750a91f1a89f82cc8eb1b19fa8779d22` — **СОВПАДАЕТ**
- `tools/docs/l4desk/fixtures/mqtt_presence_lifecycle.json`: `f6a59507fc9cbed6c2f4bf707360affedb6344cac01b7f49b12d8cf3cff08e28` — **СОВПАДАЕТ**
- `tools/docs/l4desk/fixtures/l4rtp_wire_protocol.json`: `eb8500895d8f679cd0baa59e150c8b94e8a78d8eca5b7c9f086654c066c35277` — **СОВПАДАЕТ**
- `tools/docs/l4desk/fixtures/baseline_capabilities.json`: `375412eaa61e31e72b2ea5f002862a1d1f02becdd4626a71af31d9400df560cb` — **СОВПАДАЕТ**
- `https://l4tools-generic.ar.cloud.ru/l4tools/1.7.7/l4setup.exe`: `874f5444d2d4cc9bdee39e7c25a1265a2dd98f388aca49ef205ffb764531cd88` — **ПОДТВЕРЖДЕНО**

#### 2. H-L4D-00B-IOT-v1 (iot-rpc-rest-app / Device & RPC)
- `docs/l4desk/handoffs/L4D-00B-IOT-report.md`: `136a65867165f6e33f55ef9c48054cd1020fb5d8f296bc4e62437032e0ceb7d8` — **ПОДТВЕРЖДЕНО**
- `app-service/tests/core/test_l4d_00b_baseline_fixtures.py`: `a6a936fd972bdd6d04fe02290b8b14d852f0b8d1588cc479c0958a90c2e0b142` — **ПОДТВЕРЖДЕНО**

#### 3. H-L4D-00C-PB-v1 (ProcessingBackend / Сертификаты & DB миграции)
- `ProcessingBackend/docs/l4desk/handoffs/L4D-00C-PB-report.md`: `55aa7353f518edb6af1beec73622496139bbb70e5e8d84ccd4ad887a510b42cc` — **СОВПАДАЕТ**

#### 4. H-L4D-00D-MEDIA-v1 (l4media / Медиаконтур)
- `l4media/docs/l4desk/handoffs/L4D-00D-MEDIA-report.md`: `e038e84838a27ea87ca389568215ae9c45886781eb3c262e18605d59273461b4` — **СОВПАДАЕТ**

#### 5. H-L4D-00E-MB-v1 (MenuBuilder / Коммерческий & UX контур)
- `MenuBuilder/docs/l4desk/handoffs/L4D-00E-MB-report.md`: `cdae906ca929b14235b499331e7a562727a5c694a49ef6939714467f19891279` — **СОВПАДАЕТ**
- `MenuBuilder/docs/l4desk/snapshots/openapi_baseline.json`: `3514eff4b7e0e1654314518564b5f290d155c139bc86eb0af04c32917e89c301` — **СОВПАДАЕТ**
- `MenuBuilder/docs/l4desk/snapshots/inventory_baseline.json`: `31896fcace9f6f8331b8938cebb2913f28b2c9e19e7b69725a3cacd659211a28` — **СОВПАДАЕТ**

#### 6. H-L4D-00F-SHARED-v1 (shared / etranprocessing_db)
- `shared/docs/l4desk/handoffs/L4D-00F-SHARED-report.md`: `e96ffab67cd53ef823afe88506b693305e22386b14331b2fe3aed6452235be21` — **СОВПАДАЕТ**

### 2.3. Итог Contract Gate
- Маркеры `TBD`, `TODO`, `UNKNOWN` в нормативных полях полностью отсутствуют.
- Все блоки имеют статус `ACCEPTED` и приняты в журнале `contract-handoff.md`.
- Цепочка потребителей каскада соблюдена: каждый продюсер указал `L4D-00G-DOCS` в числе целевых потребителей.
- Блокировок `BLOCKED_CONTRACT` нет. Contract Gate пройден успешно.

---

## 3. Центральная матрица версий и компонентов (Central Baseline Version Matrix)

| Компонент / Проект | Стек технологий | Принятая версия | Ревизия схемы / API | Коммит / Статус развертывания | Доказательная база (Evidence) |
|---|---|:---:|:---:|---|---|
| **tools** (Агент L4Tools) | C / Win32 / SChannel | **1.7.7** | N/A (Wire v1) | `cff9ddfb4a023eb10e01cab84fe918847849a943` (`PUBLISHED`) | Артефакт `l4setup.exe`, 6 JSON-фикстур, поддержка Win7 SP1 / Win10 / Win11, L4RTP/1, mTLS SChannel |
| **iot-rpc-rest-app** | Python 3.12 / FastAPI / RabbitMQ / MQTT | **0.2.1** | `2026_08_30_0003` | `de431c15ca0064a9c2cbd3d9233d0b9921d85cff` (`DEPLOYED` prod) | Контейнер `app1` на `87.242.100.34`, 333 теста (в т.ч. 12 тестов baseline-фикстур), топология очередей `srv.*` / `dev.*` |
| **ProcessingBackend** | Python 3.14 / FastAPI / asyncpg / Alembic | **1.0.0** | Alembic head `026` | `3cec17844193e7b0cf094f2018380afe6bb14498` (`DEPLOYED` prod) | Контейнер `processing-backend` на `87.242.100.34`, sole authority миграций, mTLS авторизация, PIN/CSR API |
| **l4media** | C (Ingress) / Janus Gateway / Nginx | **1.0.0** | L4RTP/1 | `47c9b3788aca3673effce91f372c0ebd66096069` (`DEPLOYED` prod) | Контейнеры `l4media-ingress`, `l4media-janus`, `l4media-nginx` на `87.242.100.34`, порты :8443, :8088, :8188 |
| **MenuBuilder** | Python 3.14 / React 19 / AntD v6 | **0.1.0** | REST OpenAPI v1 | `dabccacf7d9d7227d898af6f4f50e12ca9bf3f99` (`DEPLOYED` prod) | Контейнер `menubuilder-backend` + SPA на `87.242.100.34`, 289 backend + 20 frontend тестов, единые seams |
| **shared** (`etranprocessing_db`) | Python 3.14 / SQLAlchemy 2.0 | **0.1.0** | SQLAlchemy 2.0 Base | `97094aedf52bb6d1c8285d8df30d7346307cb946` (`DEPLOYED` local) | Пакет `etranprocessing-db 0.1.0`, 31 модель данных, чистый тонкий декларативный слой, 0 ошибок linter |

---

## 4. Сквозная карта идентификаторов и проверка согласованности (Identifier Mapping)

Сверка моделей идентификаторов между всеми участниками каскада подтверждает полную совместимость:

| Идентификатор | Семантика и формат | Проекты-источники | Проекты-потребители | Согласованность / Правила маппинга |
|---|---|---|---|---|
| `sn` | Серийный номер киоска/ПК (ASCII, 9–10 симв. classic, до 23+ extended) | `tools` (CN сертификата) | `ProcessingBackend`, `iot-rpc-rest-app`, `l4media`, `MenuBuilder` | Единый сквозной ключ. В mTLS извлекается из `CN={SN}` сертификата. Неизменен на всех уровнях. |
| `device_id` | Целочисленный номер устройства (legacy integer kiosk ID, e.g. 773) | `ProcessingBackend` / `shared` (`terminals.device_id`) | `MenuBuilder`, `iot-rpc-rest-app` | Используется для обратной совместимости в URL сессий (`/devices/{device_id}/session`). |
| `terminal_id` | Первичный ключ таблицы терминалов (integer PK) | `shared` (`terminals.id`) | `ProcessingBackend`, `MenuBuilder` | Внутренний суррогатный ключ сущности терминала в БД. |
| `org_id` / `tenant_id` | Идентификатор организации/арендатора (integer) | `MenuBuilder` (JWT claim `org_id`) | `ProcessingBackend`, `shared` (`orgs.org_id`) | Строго преобразуется в `int` на границе auth. В будущих моделях `fin_*` поле называется `tenant_id` (FK к `orgs.org_id`). |
| `user_id` | Идентификатор пользователя (integer PK) | `shared` (`users.id`) | `MenuBuilder` | Идентификатор оператора/пользователя в JWT и аудитных записях. |
| `session_id` | UUID технической сессии удалённого управления | `iot-rpc-rest-app` | `MenuBuilder`, `tools` | Создаётся при старте RPC сессии, отслеживается по всему жизненному циклу. |
| `stream_instance_id` | UUID активной видеотрансляции | `tools`, `MenuBuilder` | `l4media`, `iot-rpc-rest-app` | Управляет единичным видеопотоком с терминала. |
| `lease_id` | UUID монопольного владения удалённым вводом (input control) | `iot-rpc-rest-app` | `MenuBuilder` (WebSocket) | Обеспечивает единовременный ввод оператора; предотвращает интерференцию команд. |
| `mountpoint_id` | Целочисленный номер точки трансляции Janus WebRTC (e.g. 1001) | `l4media-janus` / `routes` | `MenuBuilder` (VideoPlayerScreen) | Сопоставляется 1-к-1 с терминалом `sn` в `l4media-ingress`. |
| `pin` | 6-значный одноразовый числовой пароль инициализации сертификата | `ProcessingBackend.certificates` / `mcp-pin-server` | `MenuBuilder`, `tools` (l4setup) | Одноразовый enrollment код; после выпуска сертификата статус переходит в `used`. |
| `order_id` | UUID заказа в коммерческом биллинге | `MenuBuilder` (`billing_orders`) | `shared` (`billing_orders.id`, UID) | Идентификатор коммерческой транзакции пополнения/заказа. |

---

## 5. Матрица владения данными и контурами ответственности (Data Ownership & Boundaries)

В соответствии с разделами 3, 5 и 17 `l4desk-architecture.md`:

| Область ответственности | Проект-владелец | Источник истины (Single Source of Truth) | Нормативные инварианты |
|---|---|---|---|
| **Учётные записи, тенанты, роли** | `MenuBuilder` | PostgreSQL `users`, `orgs`, `user_sessions` | Строгая изоляция по `org_id`. Все внешние пользователи L4Desk получают `role = 5`. |
| **Бизнес-карточка терминала** | `MenuBuilder` | PostgreSQL `terminals`, `licenses` | Привязка к `org_id`, имя, порядок в UI, признак льготного терминала. |
| **Выпуск и учёт сертификатов** | `ProcessingBackend` | PostgreSQL `terminal_cert_history`, `certificate_pins` | Единственный авторитет генерации и погашения PIN, проверки CSR и привязки `cert_serial`. |
| **Миграции схемы БД** | `ProcessingBackend` | `ProcessingBackend/backend/alembic` (head `026`) | **Sole authority** для всей структуры БД. Ни один другой сервис не запускает Alembic-миграции. |
| **Общие ORM-модели (Shared)** | `shared/etranprocessing_db` | Пакет `etranprocessing-db` (31 модель) | Тонкий декларативный слой. Никакой бизнес-логики, веб-фреймворков и криптографии. |
| **Устройства и runtime-состояние** | `iot-rpc-rest-app` | In-memory `LeaseRegistry` + PostgreSQL IoT | Владеет техническим online/presence, LWT, выполнением RPC-команд. |
| **Маршрутизация сообщений и RPC** | `iot-rpc-rest-app` | RabbitMQ + MQTT брокер | Топология `srv.<SN>.*` и `dev.<SN>.*`. Никакого прямого доступа к брокеру из `MenuBuilder`. |
| **Медиатранспорт (Video Streaming)** | `l4media` | Ingress demux + Janus WebRTC Gateway | Приём L4RTP/1 по mTLS :8443, демультиплексирование в Janus RTP forwarder, раздача WebRTC. |
| **Коммерческий биллинг и субледгер** | `MenuBuilder` | PostgreSQL `fin_*` (планируется на шаге `09`) | Двойная запись, целые копейки (`BigInteger`), неизменяемый журнал проводок. |
| **Дистрибуция Агента** | `tools` | Реестр артефактов (`l4setup.exe`) | Публичный релиз 1.7.7, обратная совместимость протокола. |

---

## 6. Сквозная карта взаимодействия Provider / Consumer (Contract Map)

```text
       ┌────────────────────────────────────────────────────────┐
       │                   tools (Агент 1.7.7)                  │
       └────┬───────────────────────┬──────────────────────┬─────┘
            │ mTLS CSR /cert        │ MQTT/RPC             │ L4RTP/1
            │ (:443)                │ (dev/srv topics)     │ (:8443)
            ▼                       ▼                      ▼
┌───────────────────────┐ ┌───────────────────┐ ┌─────────────────────┐
│   ProcessingBackend   │ │ iot-rpc-rest-app  │ │       l4media       │
│  (Certificates/Auth)  │ │   (Device/RPC)    │ │   (Media Ingress)   │
└───────────┬───────────┘ └─────────┬─────────┘ └──────────┬──────────┘
            │                       │                      │
            │ REST PIN /cert audit  │ Internal REST / WS   │ WebRTC WS / SDP
            │                       │                      │ (:8188)
            ▼                       ▼                      ▼
       ┌────────────────────────────────────────────────────────┐
       │             MenuBuilder (Backend & Frontend)           │
       │     (Commercial, Tenant, Console & Video UI, Fin)      │
       └────────────────────────────┬───────────────────────────┘
                                    │
                                    │ ORM Models (Base)
                                    ▼
       ┌────────────────────────────────────────────────────────┐
       │        shared/etranprocessing_db (31 ORM Model)        │
       └────────────────────────────────────────────────────────┘
```

### Детализированные контрактные интерфейсы:

1. **`tools` (Provider) → `iot-rpc-rest-app` (Consumer):**
   - **Протокол:** MQTT 3.1.1 + JSON payload.
   - **Топики:** `dev/{SN}/req`, `dev/{SN}/res`, `dev/{SN}/out`, `dev/{SN}/evt`, `dev/{SN}/ctl`, `srv/{SN}/tsk`, `srv/{SN}/rsp`, `srv/{SN}/cmt`.
   - **Presence / LWT:** `dev/{SN}/svc` (`svc_online` / `svc_offline`), `dev/{SN}/app` (`app_online` / `app_offline`).
   - **Методы RPC:** 7000 (`CMD_DIAG_STREAM_CONTROL`), 7001 (`CMD_DIAG_EXEC`), 7002 (`CMD_DIAG_CANCEL`).

2. **`tools` (Provider) → `l4media` (Consumer):**
   - **Протокол:** L4RTP/1 over mTLS TCP :8443 (клиентский сертификат выдан `iot.leo4.ru` CA).
   - **Фрейминг:** 4-байтовый префикс длины (Big-Endian) + пакет RTP (H.264 video).

3. **`ProcessingBackend` (Provider) → `tools` (Consumer):**
   - **Протокол:** HTTPS REST / Windows-1251 XML на эндпоинтах `/api/certificates/`.
   - **Операции:** `?function=check&pin={pin}`, `?function=setup` (с телом PKCS#10 CSR).

4. **`ProcessingBackend` (Provider) → `MenuBuilder` (Consumer):**
   - **Протокол:** REST API `/api/certificate-pin/` + MCP server `mcp-pin-server`.
   - **Операции:** генерация PIN, отзыв PIN, аудит истории сертификатов терминала.

5. **`iot-rpc-rest-app` (Provider) → `MenuBuilder` (Consumer):**
   - **Протокол:** Internal REST API + WebSocket Console Proxy на порту :8000.
   - **Эндпоинты:** `/api/v1/diagnostics/` (управление сессиями и командами консоли).
   - **Ввод оператора:** низколатентный WebSocket канал `/api/v1/video/control/ws/lease/{lease_id}`.

6. **`l4media` (Provider) → `MenuBuilder` (Consumer):**
   - **Протокол:** Janus WebRTC Gateway WebSocket API (`/janus-ws` на порту :8188).
   - **Эндпоинты Ingress:** HTTP API :9100 (`/health`, `/stats`, `/routes`).

7. **`shared` (Provider) → `ProcessingBackend` & `MenuBuilder` (Consumers):**
   - **Интерфейс:** Python-пакет `etranprocessing_db`, единый DeclarativeBase SQLAlchemy 2.0.

---

## 7. Разделение статусов: Фактический Baseline vs Целевая Архитектура

Для исключения ложных предпосылок в последующих шагах каскада зафиксировано строгое разделение:

### 7.1. Фактически реализовано и подтверждено в Baseline (`IMPLEMENTED & VERIFIED`)
- **Агент 1.7.7:** бинарная сборка `l4setup.exe`, исполнение консольных команд (метод 7001) с чанками вывода, отмена (метод 7002), запуск видеопотока (метод 7000), управление клавиатурой/мышью через low-latency ctl, LWT-статусы `svc` и `app`.
- **Сертификатный контур:** Nginx mTLS валидация, проверка CN={SN} и серийного номера в БД, генерация 6-значных PIN, подписание CSR через CA, аудит ingress-появлений сертификатов.
- **Медиаконтур:** Nginx stream TLS :8443 с профилем `@SECLEVEL=1` (совместимость с Windows 7), декапсуляция L4RTP/1 в `l4media-ingress`, ретрансляция в Janus WebRTC Gateway :8088/:8188, динамические маршруты по API.
- **Коммерческий и UX контур:** единые экраны `VideoPlayerScreen` + `RemoteControlOverlay` и `DeviceConsoleTab`, многотенантная изоляция по `org_id`, роли пользователей 1, 3, 4, биллинг лицензий киосков в целых копейках.
- **База данных:** 31 унифицированная модель данных в `shared/etranprocessing_db`, цепочка миграций Alembic с вершиной `026` в `ProcessingBackend`.

### 7.2. Целевая архитектура MVP — запланировано к реализации (`TARGET ARCHITECTURE / SCHEDULED`)
- **Публичная саморегистрация:** регистрация пользователя, email-токены подтверждения, атомарное создание тенанта и назначение `role = 5` — *запланировано в шаге `L4D-05-MB`*.
- **Финансовое ядро и субледгер (`fin_*`):** модели двойной записи `FinAccount`, `FinLedgerTransaction`, `FinLedgerEntry`, суточные агрегаты `FinUsageDaily` — *запланировано в шагах `L4D-04A-SHARED`, `L4D-04B-PB`, `L4D-04C-MB`, `L4D-09-MB`*.
- **Тарифные планы и биллинговый цикл:** индивидуальный расчётный цикл тенанта, постоянный бесплатный 1-й терминал, суточный пул 120 минут, округление до рубля — *запланировано в шаге `L4D-10-MB`*.
- **Платежи:** интеграция с ЮKassa (webhook/polling) и регистрация ручных банковских платежей юрлиц — *запланировано в шаге `L4D-11-MB`*.
- **Entitlement, Grace и Уведомления:** 3-дневный льготный период (grace) от границы цикла, автоматическая блокировка запуска сессий, email-нотификации `-7/-3/-1` дней — *запланировано в шаге `L4D-12-MB`*.
- **Хаб Superuser:** 5 вкладок мониторинга (регистрации, терминалы, сессии, лицензии/финансы, уведомления/ошибки) со сквозным поиском по correlation_id — *запланировано в шаге `L4D-14-MB`*.
- **Единый Session Lock и Graceful Stop:** глобальный мьютекс взаимного исключения консоли и видео, техническое завершение сессий по таймауту/команде — *запланировано в шаге `L4D-07-IOT`*.
- **Durable Event Feed с курсорами:** надёжная доставка событий жизненного цикла сессий из IoT в MenuBuilder через HTTP с курсорами — *запланировано в шаге `L4D-02-IOT`*.
- **Архивирование технических подробностей:** помесячная выгрузка JSONL.GZ с манифестами и сверкой контрольных сумм — *запланировано в шагах `L4D-15A-C`, `L4D-16-MB`*.

---

## 8. Реестр выявленных технических рисков и разрывов (Gaps Inventory)

Все технические риски, зафиксированные в отчётах продюсеров `00A–00F`, категоризированы и привязаны к соответствующим этапам каскада:

| Gap ID | Проект | Описание риска / разрыва | Влияние | Запланированное решение в каскаде |
|---|---|---|---|---|
| `GAP-01` | `tools` | Прямое сочетание `Ctrl+Alt+Del` перехватывается ядром Windows SAS | Невозможно разблокировать защищённый экран отправкой обычных скан-кодов | Использование специального RPC-действия `shortcut_action` (`L4D-01A-TOOLS`) |
| `GAP-02` | `tools` | Отклонение пользовательского ввода при заблокированной сессии Windows | Потеря событий ввода до входа пользователя | Нормативная фиксация в спецификации совместимости (`L4D-01A-TOOLS`) |
| `GAP-03` | `tools` | Требование обновления KB3140245 на Windows 7 SP1 для TLS 1.2 | Ошибка mTLS рукопожатия на непропатченных устаревших ОС | Требование в дистрибутивном манифесте мастера установки (`L4D-01A-TOOLS`) |
| `GAP-04` | `iot` | Хранение `LeaseRegistry` и pending-команд в памяти процесса (`WEB_CONCURRENCY=1`) | Невозможность горизонтального масштабирования воркеров без потери состояния | Инвариант единого процесса до внедрения Redis/DB locks (`L4D-07-IOT`) |
| `GAP-05` | `iot` | Отсутствие персистентного потока событий с курсорами | Риск пропуска биллинговых фактов при рестарте сервиса | Разработка durable event feed с курсорами (`L4D-02-IOT`) |
| `GAP-06` | `iot`/`mb` | Отсутствие сквозного взаимного исключения видео и консоли | Возможен одновременный запуск видео и консоли на одном терминале | Реализация глобального Session Lock (`L4D-07-IOT` + `L4D-08B-MB`) |
| `GAP-07` | `pb` | Отсутствие криптографической проверки подписи CSR перед вызовом CA | Потенциальный прием некорректно сформированных CSR-запросов | Добавление строгой валидации структуры CSR (`L4D-06A-PB`) |
| `GAP-08` | `pb` | Конкурентный зазор без `SELECT FOR UPDATE` при проверке PIN | Теоретическая гонка при параллельных запросах активации одного PIN | Добавление явных строковых блокировок в транзакции (`L4D-06A-PB`) |
| `GAP-09` | `pb` | Невозможность безопасного повтора setup при обрыве сети после списания PIN | Ошибка терминала при сетевом сбое во время получения сертификата | Идемпотентный механизм повторной выдачи по сессии (`L4D-06A-PB`) |
| `GAP-10` | `media` | Динамические маршруты в `l4media-ingress` хранятся только в памяти | Сброс динамических трансляций при рестарте контейнера ingress | Идемпотентное пересоздание маршрутов и сохранение состояния (`L4D-08A-MEDIA`) |
| `GAP-11` | `media` | Нулевой swap на прод-сервере `87.242.100.34` и риск OOM при росте Janus | Аварийная остановка контейнера при превышении лимита 512M RAM | Контроль лимитов ресурсов и unit-бюджетов (`L4D-08A-MEDIA`) |
| `GAP-12` | `shared`/`pb` | Отсутствие моделей и таблиц `fin_*` в базе данных | Невозможность ведения финансового субледжера | Декларативные expand-модели и Alembic миграция (`L4D-04A-C`) |
| `GAP-13` | `mb` | Отсутствие публичной формы саморегистрации и email-верификации | Невозможность автономного подключения новых клиентов | Реализация саморегистрации и email flow под флагом (`L4D-05-MB`) |

---

## 9. Нормативные решения, которые обязан фактически зафиксировать этап 01

В соответствии с реестром каскада промптов (раздел 18 `l4desk-architecture.md`), этап `01` состоит из трёх шагов:
- `L4D-01A-TOOLS — Опубликовать Agent Compatibility Contract v1` (scope: `tools`);
- `L4D-01B-IOT — Реализовать provider совместимости Agent Contract v1` (scope: `iot-rpc-rest-app`);
- `L4D-01C-DOCS — Зарегистрировать принятую пару Agent/IoT контрактов` (scope: `l4desk-service`).

Для обеспечения безошибочного исполнения этап `01` обязан зафиксировать следующие решения:

1. **Неизменность протокола Агента (Zero Protocol Break):**  
   Запрещено вносить какие-либо изменения в формат передачи данных опубликованного Агента 1.7.7. Все существующие названия MQTT топиков (`dev/{SN}/...`, `srv/{SN}/...`), числовые коды методов (7000, 7001, 7002) и обязательные поля полезной нагрузки должны быть зафиксированы в виде неизменяемых `golden vectors`.
2. **Формализация MQTT Presence / LWT:**  
   Сценарии LWT должны быть однозначно специфицированы:
   - Основное приложение: топик `dev/{SN}/app`, полезная нагрузка `app_online` / `app_offline`, флаг `retain=true`.
   - Вспомогательный сервис: топик `dev/{SN}/svc`, полезная нагрузка `svc_online` / `svc_offline`, флаг `retain=true`.
3. **Фиксация Capability Matrix:**  
   Входной контракт должен явно декларировать поддерживаемые возможности: исполнение консольных команд (`l4con_cmd_exec`), видеостриминг рабочего стола (`l4desk_desktop_stream`), поддержка Windows NT 6.1+ (Win7 SP1, Win10, Win11), шифрование SChannel TLS 1.2.
4. **Адаптер совместимости в `iot-rpc-rest-app` (`01B-IOT`):**  
   Проект `iot-rpc-rest-app` обязан принять артефакт контракта `01A` и обеспечить 100% прохождение тестов провайдерной совместимости против утверждённых фикстур без необходимости изменения Агента.
5. **Цепочка зависимостей:**  
   Шаг `L4D-01A-TOOLS` запускается строго с входным контрактом `H-L4D-00G-DOCS-v1`. Запуск шага `01B` без принятия артефактов `01A` запрещён.

---

## 10. Канонический candidate-блок для единого журнала (`H-L4D-00G-DOCS-v1`)

Ниже представлен блок передачи контракта, подлежащий добавлению в единый журнал `l4desk-service/docs/prompts/contract-handoff.md`:

```yaml
<!-- HANDOFF:H-L4D-00G-DOCS-v1:BEGIN -->
handoff_id: H-L4D-00G-DOCS-v1
status: ACCEPTED
contract_kinds:
  - REPORT
  - SEQUENCE_GATE
producer_prompt_id: L4D-00G-DOCS
producer_scope_project: l4desk-service
producer_report_path: l4desk-service/docs/handoffs/L4D-00G-DOCS-report.md
producer_branch: l4desk/l4d-00g-docs
producer_commit: COMMIT_HASH_PLACEHOLDER
accepted_at_utc: 2026-09-17T20:30:00Z
contract_version: 1.0.0
schema_revision: N/A
artifact_version: 1.0.0
artifact_paths:
  - l4desk-service/docs/handoffs/L4D-00G-DOCS-report.md
artifact_sha256:
  - SHA256_PLACEHOLDER
compatibility:
  backward_compatible_with:
    - 1.7.7
    - 0.2.1
    - 1.0.0
    - 0.1.0
  breaking_changes: false
  notes: Central baseline contract matrix consolidating all six Stage 00 baseline handoffs (00A-TOOLS through 00F-SHARED). Zero contract conflicts detected. Exact baselines verified and locked for Stage 01.
deployment_status: DOCS_PUBLISHED
deployed_environment: documentation
feature_flags: {}
contract_payload:
  identifiers:
    sn: ASCII string (9-10 chars classic, up to 23+ extended)
    device_id: integer kiosk identifier
    terminal_id: integer primary key in terminals table
    org_id: integer tenant organization ID (mapped to tenant_id)
    user_id: integer user ID
    session_id: UUID remote session identifier
    stream_instance_id: UUID video streaming session identifier
    lease_id: UUID remote input control lease identifier
    mountpoint_id: integer Janus WebRTC mountpoint identifier
    pin: 6-digit one-time certificate enrollment code
    order_id: UUID billing order identifier
  baselines:
    tools: version 1.7.7, L4RTP/1, methods 7000/7001/7002, LWT dev/{SN}/svc & dev/{SN}/app
    iot_rpc_rest_app: version 0.2.1, schema 2026_08_30_0003, RabbitMQ srv/dev topics, WEB_CONCURRENCY=1
    processing_backend: version 1.0.0, Alembic head 026, PIN/CSR/X.509 API, mTLS Nginx
    l4media: version 1.0.0, mTLS :8443 ingress, L4RTP/1 demux, Janus WebRTC :8088/:8188
    menubuilder: version 0.1.0, VideoPlayerScreen + RemoteControlOverlay, DeviceConsoleTab, RBAC multi-tenant
    shared_etranprocessing_db: version 0.1.0, 31 declarative SQLAlchemy 2.0 models, Thin DB Layer
  invariants:
    - No unverified architectural claims treated as implemented
    - Strict cross-project boundaries without direct DB or private queue coupling
    - Zero alternative UX flows for console/video in MenuBuilder
    - Whole minor units (kopecks) for all financial representations
    - ProcessingBackend sole authority for database schema migrations
    - Append-only cascade governance via contract-handoff.md
supersedes: []
known_risks:
  - Windows SAS Ctrl+Alt+Del hardware intercept requires shortcut_action in Agent
  - In-memory LeaseRegistry in IoT requires WEB_CONCURRENCY=1 until distributed locks (L4D-07-IOT)
  - Missing persistent event feed with cursors in IoT (scheduled for L4D-02-IOT)
  - Console and video mutual exclusion not globally unified (scheduled for L4D-07-IOT / L4D-08B-MB)
  - Concurrency gap without row lock in PB PIN setup handler (scheduled for L4D-06A-PB)
  - Dynamic media routes in memory only with 0B host swap (monitored, scheduled for L4D-08A-MEDIA)
  - fin_* models and double-entry subledger not yet implemented (scheduled for L4D-04A-C, L4D-09-MB)
  - Public user self-registration not yet implemented (scheduled for L4D-05-MB)
consumers:
  - L4D-01A-TOOLS
next_prompt_id: L4D-01A-TOOLS
<!-- HANDOFF:H-L4D-00G-DOCS-v1:END -->
```
