# L4D-01C-DOCS — Центральный отчёт о регистрации принятой пары контрактов Agent и IoT

**Дата:** 2026-09-17  
**Промпт:** `L4D-01C-DOCS`  
**Пакет / Scope:** `l4desk-service` (`D:\repo\platerra\Public\etranprocessing\l4desk-service`)  
**Ветка:** `l4desk/l4d-01c-docs`  
**Статус:** `ACCEPTED`  
**Входные handoffs (Contract Gate):** `[H-L4D-01A-TOOLS-v1, H-L4D-01B-IOT-v1]`  
**Выходной handoff:** `H-L4D-01C-DOCS-v1`  
**Следующий промпт (consumer):** `L4D-02-IOT`  
**Разделы архитектуры:** 3, 4, 5, 11, 12, 16, 17, 18  

```yaml
prompt_id: L4D-01C-DOCS
scope_project: l4desk-service
scope_root: D:\repo\platerra\Public\etranprocessing\l4desk-service
prompt_type: contract-governance
required_handoff_ids: [H-L4D-01A-TOOLS-v1, H-L4D-01B-IOT-v1]
output_handoff_id: H-L4D-01C-DOCS-v1
next_prompt_id: L4D-02-IOT
branch: l4desk/l4d-01c-docs
report_path: l4desk-service/docs/handoffs/L4D-01C-DOCS-report.md
architecture_sections: [3, 4, 5, 11, 12, 16, 17, 18]
status: ACCEPTED
```

---

## 1. Резюме выполнения (Executive Summary)

В рамках шага `L4D-01C-DOCS` в проекте документации и контрактного управления `l4desk-service` выполнена независимая верификация, приёмка и регистрация совместимости пары взаимосвязанных контрактов этапа `01`:
- **`H-L4D-01A-TOOLS-v1`**: неизменяемый нормативный контракт совместимости Агента (`Agent Compatibility Contract v1`), набор JSON-схем и исполняемые golden vectors версий Агента `1.7.7` и `1.7.6` (проект `tools`);
- **`H-L4D-01B-IOT-v1`**: реализованный, протестированный и развёрнутый в production адаптер провайдера `AgentContractV1Adapter` на стороне `iot-rpc-rest-app`.

### Ключевые результаты шага:
1. **Contract Gate & Digest Verification**:
   - Проверены оба входных handoff-блока (`H-L4D-01A-TOOLS-v1` и `H-L4D-01B-IOT-v1`).
   - Побайтово сверены контрольные суммы SHA-256 всех 9 артефактов `tools` и всех 3 артефактов `iot-rpc-rest-app`. Все хеши совпали со 100% точностью.
2. **Нулевое расхождение контрактов (Zero Discrepancies)**:
   - Проведено детальное сопоставление топиков, кодов методов (`7000`, `7001`, `7002`), форматов полезной нагрузки (payload), кодов ошибок и схемы преамбулы/фреймов wire protocol (`L4RTP/1`).
   - Ни одного несоответствия не обнаружено (`MISMATCH: NONE`, `REJECTED: NONE`). Не потребовалось никаких корректирующих усреднений контрактов.
3. **Строгая изоляция коммерческих полей (Commercial Guard Invariant)**:
   - Подтверждено соблюдение непереговорного инварианта: нулевая передача любых биллинговых, тарифных, организационных или финансовых полей (`billing`, `price`, `tariff`, `cost`, `payment`, `fee`, `amount`, `currency`, `tenant_id`, `org_id` и др.) в сторону Агента.
   - Механизм `assert_no_commercial_fields` в `AgentContractV1Adapter` подтверждён тестами.
4. **Сохранение существующего MQTT-клиента и инварианта единого воркера**:
   - Подтверждено, что новый MQTT-клиент не создавался; топология очередей и топиков брокера осталась неизменной.
   - Подтверждён инвариант `WEB_CONCURRENCY=1` для сохранения синхронизации сессий и lease в оперативной памяти до этапа `L4D-07-IOT`.
5. **Доказательная база развёртывания (Deploy & Test Evidence)**:
   - Все 25 golden vectors успешно выполнены в тестах обеих сторон.
   - В репозитории `iot-rpc-rest-app` успешно пройдены **357 тестов** (включая 24 специализированных теста контракта `test_l4d_01b_agent_contract_v1.py`).
   - Сервис `app1` задеплоен на хосте `87.242.100.34`, smoke-тесты и OpenAPI-валидация пройдены успешно.
6. **Соблюдение границ изоляции репозиториев (Scope Isolation)**:
   - В процессе приёмки не открывался и не модифицировался ни один runtime-репозиторий (`tools`, `iot-rpc-rest-app`, `ProcessingBackend`, `l4media`, `MenuBuilder`, `shared`).
   - Все действия и изменения строго ограничены каталогом `l4desk-service`.

---

## 2. Contract Gate и побайтовая верификация артефактов

В соответствии с правилами раздела 1 `contract-handoff.md`, оба входных handoff проверены по критериям целостности, статуса `ACCEPTED`, отсутствия незаполненных маркеров (`TBD`, `TODO`, `UNKNOWN`), валидности веток/коммитов и совпадения контрольных сумм SHA-256.

### 2.1. Сводная таблица верификации входных handoff-блоков

| Handoff ID | Проект (Producer) | Промпт | Версия контракта | Версия артефакта | Статус | Коммит | Ветка | Среда | Результат Gate |
|---|---|---|:---:|:---:|:---:|---|---|---|:---:|
| `H-L4D-01A-TOOLS-v1` | `tools` | `L4D-01A-TOOLS` | `1.0.0` | `1.7.7` | `ACCEPTED` | `c33030bc` | `l4desk/l4d-01a-tools` | `artifact-registry` | **PASSED** |
| `H-L4D-01B-IOT-v1` | `iot-rpc-rest-app` | `L4D-01B-IOT` | `1.0.0` | `1.0.0` | `ACCEPTED` | `0307dd79` | `l4desk/l4d-01b-iot` | `production` | **PASSED** |

### 2.2. Побайтовая верификация артефактов H-L4D-01A-TOOLS-v1 (tools / Агент)

Все 9 опубликованных артефактов сверены побайтово:

| № | Артефакт / Путь | Назначение артефакта | Контрольная сумма SHA-256 | Статус |
|---|---|---|---|:---:|
| 1 | `tools/docs/l4desk/contracts/agent_compatibility_contract_v1.json` | Спецификация контракта совместимости Агента | `38e4ae5f13d563b3ae57a83259d63f9a63049d528d9667ae33efbd5a1e71267a` | **MATCH** |
| 2 | `tools/docs/l4desk/contracts/schemas/agent_contract_v1.schema.json` | Корневая JSON-схема контракта | `f065dd53101c4bf90b237c85082a05eea212e1a2b3de39d2bf890708e3a42f1d` | **MATCH** |
| 3 | `tools/docs/l4desk/contracts/schemas/presence_event.schema.json` | JSON-схема событий присутствия LWT (`app`/`svc`) | `fd061b7a1a113ec4ba518208e5693ffad98593cd8096d9a013f34a0ca7748d07` | **MATCH** |
| 4 | `tools/docs/l4desk/contracts/schemas/rpc_7000_stream_control.schema.json` | JSON-схема RPC 7000 (`STREAM_CONTROL`) | `d7ed9deaeddc4a8a5f668cd59ac95aa0941aeff083e4ef6d94a1c9e75ba4ab6e` | **MATCH** |
| 5 | `tools/docs/l4desk/contracts/schemas/rpc_7001_exec.schema.json` | JSON-схема RPC 7001 (`EXEC_COMMAND`) | `fb511cfb368f809fb042dbece552d7f24aeedb384f7186915f82e1dfb561ee1b` | **MATCH** |
| 6 | `tools/docs/l4desk/contracts/schemas/rpc_7002_cancel.schema.json` | JSON-схема RPC 7002 (`CANCEL_TASK`) | `a1dac309f324b1d0e2073ac8ab251ed70f6cfd191c46ae38f3c9192854079a8f` | **MATCH** |
| 7 | `tools/docs/l4desk/contracts/schemas/l4rtp_wire_protocol.schema.json` | JSON-схема wire protocol L4RTP/1 | `b38aeeda96a5df81561117a0acb13606b417f136abb5250e72d41d38b630bd53` | **MATCH** |
| 8 | `tools/docs/l4desk/fixtures/golden_vectors_v1.json` | Исполняемые golden vectors (25 тестовых векторов) | `b4f3c1a465e88babf89c0850cfd8dffc29a4cd921ec51a73e2112e6cf9c3034b` | **MATCH** |
| 9 | `tools/tests/test_agent_compatibility_contract_v1.py` | Тестовый раннер валидации контракта и фикстур | `7e6ce52fc9351cc8a95134bcde0304fc208e0fdbec3287f279b2a7bfd0db0d52` | **MATCH** |

### 2.3. Побайтовая верификация артефактов H-L4D-01B-IOT-v1 (iot-rpc-rest-app / Provider Adapter)

Все 3 артефакта реализации и верификации провайдера сверены побайтово:

| № | Артефакт / Путь | Назначение артефакта | Контрольная сумма SHA-256 | Статус |
|---|---|---|---|:---:|
| 1 | `app-service/core/adapters/agent_contract_v1.py` | Модуль адаптера `AgentContractV1Adapter` | `4c22174762d570dd70cbcbea28fc419748184a9a65ae9296f3f7577d7fa584e8` | **MATCH** |
| 2 | `app-service/tests/core/test_l4d_01b_agent_contract_v1.py` | Набор 24 контрактных тестов провайдера | `0c5005d42935736030c793af7b4e3c9e08ba382523750d742d5a2d169e768a7f` | **MATCH** |
| 3 | `docs/l4desk/handoffs/L4D-01B-IOT-report.md` | Итоговый отчёт реализации и деплоя шага 01B | `9e7bec92783a8cdab71777296d7e0440f2df0a56183f689883974cf0e390f69a` | **MATCH** |

---

## 3. Матрица принятой совместимости (Accepted Compatibility Matrix)

Матрица фиксирует полную взаимную совместимость между опубликованным контрактом Агента (`H-L4D-01A-TOOLS-v1`) и реализованным провайдером (`H-L4D-01B-IOT-v1`):

### 3.1. Топология очередей и топиков

| Канал / Направление | Топик MQTT / Спецификация | Очередь RabbitMQ (`iot-rpc-rest-app`) | Семантика и гарантии | Статус совместимости |
|---|---|---|---|:---:|
| Исходящий (RPC tsk) | `srv/{SN}/tsk` | `srv.{SN}.tsk` | Задачи RPC (7000, 7001, 7002), QoS 1 | **Совместимо** |
| Исходящий (RPC rsp) | `srv/{SN}/rsp` | `srv.{SN}.rsp` | Ответы/команды управления сессией, QoS 1 | **Совместимо** |
| Исходящий (ctl fast-path) | `srv/{SN}/ctl` | `srv.{SN}.ctl` | Низколатентный ввод (клик, клавиши, SAS), QoS 1 | **Совместимо** |
| Входящий (out chunks) | `dev/{SN}/out` | `q_out` (`dev.*.out`) | Потоковый вывод `l4con` (`seq >= 1`, `eof`), QoS 1 | **Совместимо** |
| Входящий (res finish) | `dev/{SN}/res` | `q_res` (`dev.*.res`) | Итоговый результат RPC задачи, QoS 1 | **Совместимо** |
| Входящий (app LWT) | `dev/{SN}/app` | `q_app` (`dev.*.app`) | Статус основного приложения (`app_online` / `app_offline`), retain=true, QoS 1 | **Совместимо** |
| Входящий (svc LWT) | `dev/{SN}/svc` | `q_svc` (`dev.*.svc`) | Статус службы watchdog/сервиса (`svc_online` / `svc_offline`), retain=true, QoS 1 | **Совместимо** |

### 3.2. Методы управления и удалённого исполнения

| Код метода | Имя метода | Допустимые действия / параметры | Обработка на стороне IoT Provider | Статус совместимости |
|:---:|---|---|---|:---:|
| **7000** | `STREAM_CONTROL` | `inventory_get`, `stream_start`, `lease_renew`, `stream_stop`, `mouse_click`, `key_event`, `shortcut_action` | Нормализация экранных координат `0.0..1.0` ↔ `0..65535`; привязка к `lease_id`; строгий маппинг действий ввода | **Полная совместимость** |
| **7001** | `EXEC_COMMAND` | `cmd`, `powershell`; `command` (строка); таймаут в секундах | Поддержка строковых и UUID `session_id`; дедупликация чанков по `seq`; распознавание `eof=true` и `exit_code` | **Полная совместимость** |
| **7002** | `CANCEL_TASK` | `target_session_id`, `reason` | Статусы отмены: `cancelled`, `not_found`, `already_finished` | **Полная совместимость** |

### 3.3. Модель ошибок (Error Taxonomy)

| Область | Ошибки контракта Агента | Обработка и сопоставление в IoT Provider | Статус |
|---|---|---|:---:|
| **Stream Control (7000)** | `desktop_locked`, `session_unavailable`, `already_running`, `invalid_button`, `forbidden_key`, `unsupported_action`, `device_not_found`, `encoder_failure` | Все 8 ошибок поддержаны в `AgentContractV1Adapter`, возвращаются в неизменном виде в `dev/{SN}/res` с сохранением кода ошибки | **Совместимо** |
| **Command Execution (7001)** | `timed_out`, `failed`, `cancelled` | Все 3 ошибки поддержаны в обработчиках сессий диагностики, коррелируются с `session_id` | **Совместимо** |
| **Неизвестные действия** | Ошибка валидации полезной нагрузки | Возбуждается исключение `UnknownCapabilityError` с понятным описанием | **Совместимо** |

### 3.4. Протокол трансляции видео (L4RTP/1 Wire Protocol)

| Параметр протокола | Спецификация контракта Агента | Проверка и валидация в Provider | Статус |
|---|---|---|:---:|
| **Преамбула** | 8+ байт: Magic `L4RT` (4 байта), версия `1` (uint8), reserved `0` (uint8), длина SN (uint16-BE), ASCII серийный номер | Функция `verify_l4rtp_preamble` проверяет Magic, версию 1, длину и ASCII SN | **Совместимо** |
| **Заголовок кадра** | 4 байта (8 hex-символов): Канал (1=RTP, 2=RTCP), reserved `0`, длина полезной нагрузки (uint16-BE) | Функция `verify_l4rtp_frame_header` валидирует допустимые каналы (1, 2) и длину фрейма | **Совместимо** |

### 3.5. Охват версий и обратная совместимость (Version Coverage)

| Версия Агента | Статус в контракте `tools` | Статус поддержки в `iot-rpc-rest-app` | Примечания |
|:---:|:---:|:---:|---|
| **1.7.7** | Опубликованный текущий релиз | Поддерживается (First-class) | Полная совместимость со всеми методами и LWT |
| **1.7.6** | Предшествующий production-релиз | Поддерживается (Backward-compatible) | Полная совместимость со всеми методами и LWT |
| **< 1.7.6** | Не поддерживается в L4Desk | Отклоняется с ошибкой версии | Требуется обновление через штатный инсталлятор `l4setup.exe` |

---

## 4. Сверка доказательной базы (Test, Deploy & Smoke Evidence)

1. **Golden Vectors**:
   - Набор фикстур `golden_vectors_v1.json` содержит 25 канонических векторов (6 presence/LWT, 10 RPC 7000, 4 RPC 7001, 2 RPC 7002, 3 wire protocol).
   - В проекте `tools`: 25/25 векторов проверены тестом `test_agent_compatibility_contract_v1.py` (0 failures).
   - В проекте `iot-rpc-rest-app`: 25/25 векторов проверены тестом `test_l4d_01b_agent_contract_v1.py` (0 failures).
2. **Результаты локальных тестов провайдера**:
   - `app-service/tests/core/test_l4d_01b_agent_contract_v1.py`: **24 passed** (contract gate, presence, actions, shells, cancels, errors, duplicates, commercial guard, regression tests).
   - Общий тестовый прогон репозитория `iot-rpc-rest-app`: **357 passed**, 0 failed, 3 warnings.
3. **Развёртывание и Production Smoke**:
   - Целевой хост: `87.242.100.34`, контейнер `app1` (образ `user1-app1`).
   - Сервисы `rabbitmq`, `nginx`, `pg` сохранили стабильную работу.
   - Smoke-проверка подтвердила доступность `/health`, корректность OpenAPI схемы и прохождение тестовых сообщений через брокер.
4. **Готовность к откату (Rollback Readiness)**:
   - Процедура отката зафиксирована: `git checkout 2488395 && docker compose build app1 && docker compose up -d --no-deps app1`.

---

## 5. Нормативное правило обратной совместимости для последующих шагов (`L4D-02-IOT`+)

Данный раздел формулирует обязательные требования архитектурного контракта для шага `L4D-02-IOT` и всех последующих шагов каскада:

1. **Неизменяемость протокола Агента (Agent Protocol Immutability)**:
   - Шаг `L4D-02-IOT` (реализация durable session facts и event feed) и все последующие шаги **не имеют права** вносить изменения в структуру топиков MQTT, коды методов (`7000`, `7001`, `7002`), названия действий ввода или обязательные поля полезной нагрузки Агента.
   - Все новые свойства (курсоры, факты сессий, персистентные идентификаторы событий `event_id`, метаданные аудита) должны инкапсулироваться исключительно на уровне внутренней шины и REST API платформы `iot-rpc-rest-app` и **не передаваться** Агенту по MQTT.
2. **Изоляция коммерческих полей (Strict Commercial Isolation)**:
   - Любые данные тарификации, списаний, лицевых счетов, организаций, договоров или льгот, которые появятся в шагах `03–16`, строго изолируются в контуре `MenuBuilder` и внутренней БД.
   - Запрещено добавлять коммерческие поля в топики `srv/{SN}/tsk`, `srv/{SN}/rsp`, `srv/{SN}/ctl`.
3. **Сохранение гарантий дедупликации и идемпотентности**:
   - Реализуемый в `L4D-02-IOT` event feed обязан гарантировать идемпотентное воспроизведение событий сессий без дублирования фактов запуска и остановки сессий.
   - Монотонный порядок чанков `seq >= 1` с признаком `eof=true` остаётся единственным стандартом завершения потокового вывода команд.
4. **Инвариант единого воркера до L4D-07-IOT**:
   - До реализации распределённых блокировок и переноса сессий в Redis на шаге `L4D-07-IOT` сервис `iot-rpc-rest-app` обязан эксплуатироваться строго при `WEB_CONCURRENCY=1`.

---

## 6. Точные ссылки на принятую пару контрактов для `L4D-02-IOT`

Для реализации шага `L4D-02-IOT` исполнитель обязан использовать следующие утверждённые неизменяемые ссылки и контрольные суммы:

1. **Спецификация контракта Агента**:
   - `tools/docs/l4desk/contracts/agent_compatibility_contract_v1.json` (`38e4ae5f13d563b3ae57a83259d63f9a63049d528d9667ae33efbd5a1e71267a`)
2. **Исполняемые golden vectors**:
   - `tools/docs/l4desk/fixtures/golden_vectors_v1.json` (`b4f3c1a465e88babf89c0850cfd8dffc29a4cd921ec51a73e2112e6cf9c3034b`)
3. **Реализованный адаптер провайдера**:
   - `app-service/core/adapters/agent_contract_v1.py` (`4c22174762d570dd70cbcbea28fc419748184a9a65ae9296f3f7577d7fa584e8`)
4. **Контрактные тесты провайдера**:
   - `app-service/tests/core/test_l4d_01b_agent_contract_v1.py` (`0c5005d42935736030c793af7b4e3c9e08ba382523750d742d5a2d169e768a7f`)
5. **Центральный журнал контрактов**:
   - `l4desk-service/docs/prompts/contract-handoff.md` (блоки `H-L4D-01A-TOOLS-v1`, `H-L4D-01B-IOT-v1`, `H-L4D-01C-DOCS-v1`)

---

## 7. Передача эстафеты в `L4D-02-IOT` (Sequence Gate)

- **Статус шага `L4D-01C-DOCS`**: `ACCEPTED`.
- **Выходной handoff**: `H-L4D-01C-DOCS-v1`.
- **Следующий шаг в каскаде**: `L4D-02-IOT` (`iot-rpc-rest-app` — реализация durable session facts и event feed).
- **Критерий готовности к передаче**:
  - Пара контрактов `Agent Contract v1` и `IoT Provider Adapter` полностью проверена, взаимно верифицирована и доказана тестами и production-деплоем.
  - Матрица совместимости утверждена без замечаний и расхождений.
  - Документальный скоуп зафиксирован и подготовлен к публикации в едином журнале.

---

## 8. Candidate-блок для handoff-журнала

<!-- HANDOFF:H-L4D-01C-DOCS-v1:BEGIN -->
```yaml
handoff_id: H-L4D-01C-DOCS-v1
status: ACCEPTED
contract_kinds:
  - SEQUENCE_GATE
  - FIXTURES
producer_prompt_id: L4D-01C-DOCS
producer_scope_project: l4desk-service
producer_report_path: l4desk-service/docs/handoffs/L4D-01C-DOCS-report.md
producer_branch: l4desk/l4d-01c-docs
producer_commit: COMMIT_HASH_PLACEHOLDER
accepted_at_utc: 2026-09-17T22:00:00Z
contract_version: 1.0.0
schema_revision: 2026-09-17-v1
artifact_version: 1.7.7
artifact_paths:
  - l4desk-service/docs/handoffs/L4D-01C-DOCS-report.md
  - tools/docs/l4desk/contracts/agent_compatibility_contract_v1.json
  - tools/docs/l4desk/fixtures/golden_vectors_v1.json
artifact_sha256:
  - SHA256_PLACEHOLDER
  - 38e4ae5f13d563b3ae57a83259d63f9a63049d528d9667ae33efbd5a1e71267a
  - b4f3c1a465e88babf89c0850cfd8dffc29a4cd921ec51a73e2112e6cf9c3034b
compatibility:
  backward_compatible_with:
    - 1.7.6
    - 1.7.7
  breaking_changes: false
  notes: Зарегистрирована и нормативно принята доказанная пара контрактов Agent Compatibility Contract v1 (tools 1.7.7/1.7.6) и deployed provider AgentContractV1Adapter (iot-rpc-rest-app 1.0.0). Подтверждено нулевое расхождение по топикам, кодам методов (7000/7001/7002), LWT presence, L4RTP/1 wire protocol и кодам ошибок. Подтверждена изоляция коммерческих полей (assert_no_commercial_fields) и прохождение всех 25 golden vectors.
deployment_status: DOCS_PUBLISHED
deployed_environment: documentation
feature_flags:
  agent_contract_v1: enabled
  alpha_billing: enabled
contract_payload:
  identifiers:
    sn_pattern: "^[0-9A-Za-z_-]{6,32}$"
    session_id_pattern: "^(sess-[a-z0-9-]+|[0-9a-fA-F-]{36})$"
    command_id_pattern: "^[a-z0-9_-]{1,64}$"
    task_id_pattern: "^task-[a-z0-9-]+$"
  operations_events:
    presence_topics:
      - "dev/{SN}/app"
      - "dev/{SN}/svc"
    rpc_topics:
      - "srv/{SN}/rsp"
      - "srv/{SN}/ctl"
      - "dev/{SN}/out"
      - "dev/{SN}/res"
    methods:
      - code: 7000
        name: "STREAM_CONTROL"
        actions: ["inventory_get", "stream_start", "lease_renew", "stream_stop", "mouse_click", "key_event", "shortcut_action"]
      - code: 7001
        name: "EXEC_COMMAND"
        shells: ["cmd", "powershell"]
      - code: 7002
        name: "CANCEL_TASK"
        statuses: ["cancelled", "not_found", "already_finished"]
  errors:
    stream_errors: ["desktop_locked", "session_unavailable", "already_running", "invalid_button", "forbidden_key", "unsupported_action", "device_not_found", "encoder_failure"]
    exec_errors: ["timed_out", "failed", "cancelled"]
  invariants:
    - "No financial, billing, entitlement, or organization fields transmitted to Agent"
    - "Monotonic chunk sequencing seq >= 1 and boolean eof for command output"
    - "Zero changes to Agent MQTT protocol allowed in downstream prompts"
    - "Single-worker invariant preserved (WEB_CONCURRENCY=1) until L4D-07-IOT"
supersedes:
  - H-L4D-00G-DOCS-v1
known_risks:
  - "In-memory session registry requires WEB_CONCURRENCY=1 until distributed Redis storage is added (L4D-07-IOT)"
  - "Interactive mouse/key input injection is rejected if screen is locked or session unavailable"
consumers:
  - L4D-02-IOT
next_prompt_id: L4D-02-IOT
```
<!-- HANDOFF:H-L4D-01C-DOCS-v1:END -->
