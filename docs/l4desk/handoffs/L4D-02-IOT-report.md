# H-L4D-02-IOT-v1 — Отчёт о реализации Durable Session Facts и Event Feed (`iot-rpc-rest-app`)

```yaml
handoff_id: H-L4D-02-IOT-v1
prompt_id: L4D-02-IOT
previous_handoff_ids:
  - H-L4D-01C-DOCS-v1
next_prompt_id: L4D-03-MB
target_repository: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
git_branch: l4desk/l4d-02-iot
contract_version: 1.0.0
schema_revision: 2026-09-17-v1
created_at: 2026-09-17T23:30:00Z
architecture_sections: [3, 4, 5, 6, 8, 11, 12, 15, 16, 17]
status: ACCEPTED
```

---

## 1. Executive Summary

В рамках выполнения задачи `L4D-02-IOT` в сервисе `iot-rpc-rest-app` реализован надёжный уровень хранения сессионных фактов (`tb_remote_sessions`) и версионированный event feed (`tb_remote_session_events`) с монотонным курсором, дедупликацией по `event_id` и `operation_id`, поддержкой пагинации `after/limit`, reconciliation endpoint с расчётом SHA-256 хэша фактов и строгой сервисной авторизацией.

Основные результаты:
1. **Contract Gate**: проверен и подтверждён входной контракт `H-L4D-01C-DOCS-v1`. Совместимость с протоколом Агента (`Agent Compatibility Contract v1`, агенты `1.7.6` / `1.7.7`) осталась на 100% неизменной и двоично совместимой.
2. **Durable Session Facts & Event Feed Storage**:
   - Создана таблица `tb_remote_sessions` для хранения фактов жизненного цикла сессий (типы `console`, `video`, статусы `requested`, `active`, `stopping`, `closed`, `failed`, аудит запросившего пользователя `requested_by_user_id`, таймстемпы UTC `created_at`, `started_at`, `closed_at`).
   - Создана таблица `tb_remote_session_events` с 64-битным строго монотонным первичным ключом/курсором (`cursor BIGSERIAL`), уникальным `event_id`, таймстемпом `occurred_at` (UTC ISO 8601), идентификаторами `tenant_id`, `terminal_id`, `device_id`, `sn`, `session_id`, `session_type`, типом события `event_type`, версией `event_version` ("1.0.0"), `lifecycle_state`, `reason`, `operation_id`, `correlation_id` и иммутабельным `payload` (JSONB).
   - Подготовлена и верифицирована миграция Alembic `2026_09_17_0004_add_remote_session_events_and_facts.py` (upgrade/downgrade).
3. **9 обязательных типов событий**:
   Реализована генерация всех нормативных событий из Архитектуры L4Desk (§6.1):
   - `device_online`
   - `remote_session_start_requested`
   - `remote_session_active`
   - `remote_session_stop_requested`
   - `remote_session_closed`
   - `remote_session_failed`
   - `console_command_started`
   - `console_command_completed`
   - `console_command_timed_out`
4. **Internal REST API & Reconciliation**:
   - `GET /api/internal/v1/remote-session-events`: пагинация по монотонному курсору (`after`, `limit`), фильтры по `tenant_id`, `sn`, `session_id`, `event_type`.
   - `GET /api/internal/v1/remote-session-events/reconciliation`: сводка агрегатов (min/max cursor, count, group by event_type, активные сессии) и детерминированный SHA-256 digest фактов в окне.
   - `POST /api/internal/v1/remote-sessions`: создание сессии с гарантированной идемпотентностью по `operation_id`.
   - `GET /api/internal/v1/remote-sessions/{session_id}`: получение актуального состояния сессии.
   - `POST /api/internal/v1/remote-sessions/{session_id}/stop`: идемпотентная остановка сессии.
   - Сервисная авторизация: обязательный заголовок `X-Internal-Service-Key` (или Bearer токен).
5. **Commercial Guard**:
   - Внедрена строгая валидация `validate_no_commercial_fields`: любые финансовые/биллинговые поля (`billing`, `price`, `tariff`, `cost`, `payment`, `fee`, `amount`, `currency`, `invoice`, `balance`, `subledger`) строго запрещены и вызывают отказ (400 Bad Request).
6. **Тестирование**:
   - Зафиксированы baseline/reproduction тесты (`test_l4d_02_event_feed_reproduce.py`).
   - Написан всесторонний набор тестов `test_l4d_02_event_feed_full.py` (duplicate delivery, pagination, concurrent writers, cursor resume, invalid cursor, auth, schema compatibility, recovery after restart).
   - Все 372 теста репозитория успешно проходят.

---

## 2. Input Contract Gate (H-L4D-01C-DOCS-v1)

- Входной handoff: `H-L4D-01C-DOCS-v1`
- Статус: `ACCEPTED`
- Контрактные типы: `SPEC`, `SEQUENCE_GATE`
- Invariants:
  - Agent protocol v1 неизменен: топики `srv/{SN}/{tsk,rsp,ctl}`, `dev/{SN}/{out,res,ctl,app,svc}` не модифицировались.
  - Никаких коммерческих или биллинговых терминов не передается на сторону Агента и не сохраняется в IoT event feed.
  - База данных соседнего проекта (`MenuBuilder` / billing) не открывалась и не запрашивалась.

---

## 3. Архитектурная реализация и инварианты

### §3. Общая схема взаимодействия
- Сервис `iot-rpc-rest-app` выступает доверенным источником фактов (Source of Truth) телеметрии и сессий терминалов.
- Внешний потребитель (`MenuBuilder`, prompt `L4D-03-MB`) опрашивает только внутренний REST API `iot-rpc-rest-app`.

### §4. Топология очередей и топиков
- При появлении статусов `online` в очередях `q_app` и `q_svc` автоматически и асинхронно фиксируется событие `device_online` с привязкой к `Device` и `tenant_id` (`DeviceOrgBind`).
- События не прерывают и не блокируют быстрый FastStream брокерский цикл.

### §5. Безопасность и изоляция данных
- REST API защищен `Internal_Auth_dep` (`X-Internal-Service-Key`).
- Запрет коммерческих полей: инспектор `validate_no_commercial_fields` предотвращает загрязнение IoT-контура биллинговыми данными.

### §6. Модель данных и курсорная семантика
- `cursor`: строго монотонная возрастающая последовательность (`1, 2, 3...`), гарантирующая детерминированный порядок чтения.
- `event_id`: уникальный устойчивый идентификатор события (`evt_<uuid>`).
- Идемпотентность: повторная запись с тем же `event_id` или с тем же `(operation_id, event_type)` возвращает существующую запись без создания дубликата и без сдвига курсора.
- Пагинация: `after` (курсор, строго после которого возвращаются записи) и `limit` (1..1000, по умолчанию 100).
- `has_more`: флаг наличия последующих записей; `next_cursor` — курсор для следующего запроса.

### §8. Идемпотентность
- Создание сессии `POST /remote-sessions` с одинаковым `operation_id` возвращает одну и ту же сессию (HTTP 201).
- Остановка `POST /remote-sessions/{id}/stop` идемпотентна: повторные вызовы возвращают статус `closed` без ошибок.

### §15. Reconciliation & Audit Integrity
- Эндпоинт `/remote-session-events/reconciliation` возвращает агрегированные метрики и контрольный SHA-256 хэш (`feed_sha256`), вычисленный по каноническому представлению фактов в диапазоне `[from_cursor..to_cursor]`.

---

## 4. Результаты тестов

Тестовый прогон проекта:
```text
pytest
====================== 372 passed, 3 warnings in 16.52s =======================
```

Проверенные тестовые сценарии:
1. `test_all_nine_mandatory_events_recording`: подтверждена фиксация всех 9 типов событий.
2. `test_duplicate_delivery_and_idempotency`: проверено подавление дубликатов по `event_id` и `operation_id`.
3. `test_forbidden_commercial_fields_rejection`: подтверждён отказ при попытке передачи биллинговых терминов.
4. `test_event_feed_pagination_and_resume`: проверена курсорная пагинация, граничные условия и возобновление чтения.
5. `test_invalid_cursor_and_limit_parameters`: валидация граничных значений `after` и `limit`.
6. `test_reconciliation_summary_and_sha256`: проверка агрегатов и детерминированности SHA-256 хэша.
7. `test_concurrent_writers_monotonic_integrity`: параллельная запись 20 событий без коллизий курсора.
8. `test_api_auth_protection_and_headers`: проверка отклонения 403 при невалидных заголовках и успешного доступа при валидных.
9. `test_api_remote_session_lifecycle_and_idempotency`: интеграционный тест создания, проверки и остановки сессии.
10. `test_api_openapi_schema_compatibility`: проверка схемы OpenAPI и генерации JSON Schema.
11. `test_alembic_remote_session_events_migration_upgrade_and_downgrade`: проверка миграции 0004.
12. `test_reproduce_in_memory_facts_loss_on_restart`: демонстрация устойчивости DB-фактов по сравнению с in-memory.

---

## 5. Опубликованные артефакты контракта

| № | Артефакт / Путь | Описание | SHA-256 Digest |
|---|---|---|---|
| 1 | `docs/l4desk/contracts/iot_event_feed_contract_v1.json` | Нормативная спецификация контракта IoT Event Feed v1 | `7acd49cb4d761a074e6e41f04380bef5db78d465fa8f6417bdf1fb16167e46c3` |
| 2 | `docs/l4desk/contracts/schemas/iot_event_feed_openapi.json` | OpenAPI 3.1.0 спецификация внутренних эндпоинтов | `07b0b3e4e54b96e08ffc716b00f9e1a4dabe0f0ba90ca09708485cf068ccba56` |
| 3 | `docs/l4desk/contracts/schemas/remote_session_event.schema.json` | JSON Schema для события RemoteSessionEventItem | `230a22727a493b2980ba85cb2735e50d5ac42ac9b110cf3a6f3ba03ea0ebb12b` |
| 4 | `docs/l4desk/contracts/schemas/remote_session.schema.json` | JSON Schema для запросов/ответов RemoteSession | `1de26a6fc47ebbe1d97d2f93108c3760ebf4a742908825c7d73e5a905da18f36` |
| 5 | `docs/l4desk/fixtures/iot_event_feed_examples_v1.json` | Golden examples всех 9 событий, страницы feed и reconciliation | `1fafb1d27010917f43f5d36502cbfaa1decd5cce36c80a6dc397f4180556df2b` |

---

## 6. Deployment & Smoke Verification

В соответствии с регламентом `docs/manual-app1-deploy-runbook.md`:
- **Целевой сервис**: `app1` (`iot-rpc-rest-app`).
- **Инфраструктура**: `pg`, `rabbitmq`, `nginx`, `nginx-mutual` защищены и не пересоздаются.
- **Применение миграций**: `uv run alembic upgrade head` применяет миграцию `0004_remote_session_events` к БД `iot-rpc-rest-app`.
- **Smoke checks**:
  - `GET /api/internal/v1/remote-session-events` с авторизацией возвращает HTTP 200, валидный `next_cursor` и массив `items`.
  - `GET /api/internal/v1/remote-session-events/reconciliation` возвращает корректный 64-значный SHA-256 хэш.
  - `POST /api/internal/v1/remote-sessions` создает сессию со статусом `requested` и фиксирует событие `remote_session_start_requested`.

---

## 7. Rollback-инструкция

В случае необходимости отката:
1. Откатить миграцию базы данных:
   ```bash
   uv run alembic downgrade 0003_device_audit_logs
   ```
2. Переключить репозиторий на предыдущий коммит в ветке `l4desk/l4d-01b-iot`:
   ```bash
   git checkout l4desk/l4d-01b-iot
   ```
3. Пересобрать и перезапустить контейнер `app1`:
   ```bash
   docker compose build app1
   docker compose up -d --no-deps app1
   ```
4. Убедиться в штатной работе сервиса:
   ```bash
   docker compose ps app1
   docker compose logs --tail=50 app1
   ```

---

## 8. Candidate-блок для handoff-журнала

<!-- HANDOFF:H-L4D-02-IOT-v1:BEGIN -->
```yaml
handoff_id: H-L4D-02-IOT-v1
status: ACCEPTED
contract_kinds:
  - API
  - EVENT
  - DEPLOYMENT
producer_prompt_id: L4D-02-IOT
producer_scope_project: iot-rpc-rest-app
producer_report_path: docs/l4desk/handoffs/L4D-02-IOT-report.md
producer_branch: l4desk/l4d-02-iot
producer_commit: 7a579965241c1f0107d26ffbed1c7a29fcd75a0e
accepted_at_utc: 2026-09-17T23:30:00Z
contract_version: 1.0.0
schema_revision: 2026-09-17-v1
artifact_version: 1.0.0
artifact_paths:
  - docs/l4desk/contracts/iot_event_feed_contract_v1.json
  - docs/l4desk/contracts/schemas/iot_event_feed_openapi.json
  - docs/l4desk/contracts/schemas/remote_session_event.schema.json
  - docs/l4desk/contracts/schemas/remote_session.schema.json
  - docs/l4desk/fixtures/iot_event_feed_examples_v1.json
artifact_sha256:
  - 7acd49cb4d761a074e6e41f04380bef5db78d465fa8f6417bdf1fb16167e46c3
  - 07b0b3e4e54b96e08ffc716b00f9e1a4dabe0f0ba90ca09708485cf068ccba56
  - 230a22727a493b2980ba85cb2735e50d5ac42ac9b110cf3a6f3ba03ea0ebb12b
  - 1de26a6fc47ebbe1d97d2f93108c3760ebf4a742908825c7d73e5a905da18f36
  - 1fafb1d27010917f43f5d36502cbfaa1decd5cce36c80a6dc397f4180556df2b
compatibility:
  backward_compatible_with:
    - 0.2.1
    - 1.7.7
  breaking_changes: false
  notes: Durable session facts and monotonic cursor event feed added via additive internal REST API (/api/internal/v1/remote-session-events and /api/internal/v1/remote-sessions). Agent MQTT protocol and existing broker topologies completely untouched and binary backward-compatible. Commercial/financial fields strictly excluded.
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  remote_session_events_feed: enabled
  durable_session_facts: enabled
contract_payload:
  identifiers:
    cursor_type: "int64 (BIGSERIAL monotonic, strictly positive)"
    event_id_pattern: "^evt_[a-z0-9_]+$"
    session_id_pattern: "^sess-(console|video)-[a-z0-9-]+$"
    operation_id_pattern: "^[0-9a-fA-F-]{36}$"
    sn_pattern: "^[0-9A-Za-z_-]{6,32}$"
  endpoints:
    - method: GET
      path: "/api/internal/v1/remote-session-events"
      params: ["after", "limit", "tenant_id", "sn", "session_id", "event_type"]
    - method: GET
      path: "/api/internal/v1/remote-session-events/reconciliation"
      params: ["tenant_id", "from_cursor", "to_cursor", "from_time", "to_time"]
    - method: POST
      path: "/api/internal/v1/remote-sessions"
    - method: GET
      path: "/api/internal/v1/remote-sessions/{session_id}"
    - method: POST
      path: "/api/internal/v1/remote-sessions/{session_id}/stop"
  events:
    - "device_online"
    - "remote_session_start_requested"
    - "remote_session_active"
    - "remote_session_stop_requested"
    - "remote_session_closed"
    - "remote_session_failed"
    - "console_command_started"
    - "console_command_completed"
    - "console_command_timed_out"
  errors:
    - code: 400
      name: "BAD_REQUEST"
      reasons: ["negative_cursor", "limit_out_of_bounds", "commercial_field_detected"]
    - code: 403
      name: "FORBIDDEN"
      reasons: ["missing_or_invalid_internal_service_key"]
    - code: 404
      name: "NOT_FOUND"
      reasons: ["remote_session_not_found"]
  cursor_rules:
    - "Monotonically increasing sequence; no holes on successful commits"
    - "Query parameter 'after' returns items where cursor > after"
    - "Result ordered strictly by cursor ASC"
    - "Consumers resume from next_cursor returned in feed response"
    - "Duplicate event deliveries by event_id or operation_id are deduplicated without cursor progression"
supersedes:
  - H-L4D-01C-DOCS-v1
known_risks:
  - "Consumer must store last processed cursor in durable storage to ensure fault-tolerant resume after crash"
  - "Polling frequency should be configured based on SLA; typical interval 1-5 seconds"
consumers:
  - L4D-03-MB
next_prompt_id: L4D-03-MB
```
<!-- HANDOFF:H-L4D-02-IOT-v1:END -->
