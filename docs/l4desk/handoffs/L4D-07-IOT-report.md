# H-L4D-07-IOT-v1 — Отчёт о реализации Unified Session Lock и Command-Aware Graceful Stop (`iot-rpc-rest-app`)

```yaml
handoff_id: H-L4D-07-IOT-v1
prompt_id: L4D-07-IOT
prompt_type: implementation-provider
target_repository: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
git_branch: l4desk/l4d-07-iot
producer_commit: c4e892f4c1dbf8f967109e8a06c3f63b0c9bd483
contract_version: 1.0.0
schema_revision: 2026-09-19-v1
contract_kinds:
  - API
  - EVENT
  - DEPLOYMENT
required_handoff_ids:
  - H-L4D-06C-MB-v1
  - H-L4D-01C-DOCS-v1
  - H-L4D-02-IOT-v1
consumers:
  - L4D-08A-MEDIA
  - L4D-08B-MB
  - L4D-12-MB
next_prompt_id: L4D-08A-MEDIA
architecture_sections: [3, 4, 5, 6, 8, 11, 12, 16, 17]
created_at: 2026-09-19T14:30:00Z
status: ACCEPTED
```

---

## 1. Executive Summary

В рамках задачи `L4D-07-IOT` в сервисе `iot-rpc-rest-app` реализован окончательный технический ownership единого session lock на устройство (`sn` / `device_id`), взаимное исключение между console и video сессиями, а также command-aware graceful stop с bounded timeout.

### Ключевые результаты реализации:
1. **Единый Session Lock & Взаимное исключение (Mutual Exclusion)**:
   - В любой момент времени для каждого устройства (`sn`) может существовать не более одной сессии в активном/переходном состоянии (`requested`, `starting`, `active`, `stopping`).
   - Попытка создания второй сессии любого типа (console блокирует video, video блокирует console, console блокирует console, video блокирует video) стабильно отклоняется с HTTP `409 Conflict` и структурированным телом ошибки `{"code": "session_busy", "active_session_id": "...", "active_session_type": "...", "active_status": "...", "sn": "..."}`.
   - Взаимное исключение гарантировано на уровне транзакций/БД через частичный уникальный индекс `uq_active_remote_session_per_sn` на таблице `tb_remote_sessions(sn)` WHERE `status IN ('requested', 'starting', 'active', 'stopping')` и сериализационный `asyncio.Lock` в runtime-сервисе.

2. **Жизненный цикл сессий (Full Lifecycle)**:
   - Реализована строгая последовательность переходов состояний:
     `requested` → `starting` → `active` → `stopping` → `closed` / `failed`.
   - Добавлен статус `starting` в `RemoteSessionLifecycleState`.
   - Добавлено событие `remote_session_starting` в `RemoteSessionEventType`.

3. **Command-Aware Graceful Stop (Console & Video)**:
   - **Console sessions**: При инициации `stop_session` статус сессии переводится в `stopping`, публикуется `remote_session_stop_requested`. Начиная с этого момента, любые новые команды запрещены и отклоняются (`ConsoleCommandForbiddenError` / HTTP 409). Сервис проверяет наличие текущей in-flight команды и ожидает её завершения либо истечения контрактного таймаута (`timeout_sec`, по умолчанию 5.0 с). Бесконечное ожидание исключено (`asyncio.wait_for`). При ответе фиксируется `console_command_completed`, при превышении таймаута — `console_command_timed_out`. После этого сессия переходит в `closed`, публикуется `remote_session_closed`, lock освобождается.
   - **Video sessions**: Штатный teardown media/stream flow — отзыв стрим-лиза в `lease_registry`, фиксация `remote_session_stop_requested` → `remote_session_closed`, освобождение lock на устройство.

4. **Event Feed (Contract 02) & Тарифицируемый интервал**:
   - Все переходы состояний немедленно публикуются в durable feed `tb_remote_session_events` со строго монотонным курсором.
   - Тарифицируемый интервал сессии ограничен строго рамками `started_at` (`active`) → `closed_at` (`closed`). Время в статусах `requested` и `starting` не тарифицируется (длительность = 0, если сессия завершилась/упала до `active`).

5. **Crash Recovery & Stale Session Eviction**:
   - Реализована детекция «зависших» сессий (`is_session_stale`): сессия признаётся stale при отсутствии heartbeat свыше порогового значения (`stale_timeout_sec`).
   - При поступлении нового запроса на сессию для устройства с «зависшей» сессией сервис автоматически эвиктит её со статусом `failed` и причиной `stale_session_timeout`, публикует `remote_session_failed` и предоставляет lock новому запросу.

6. **Agent Contract v1 Invariant**:
   - Протокол Агента, топики MQTT (`srv/<SN>/{tsk,rsp,ctl}`, `dev/<SN>/{out,res,ctl,app,svc}`), коды методов (7000, 7001, 7002) и структура payloads полностью сохранены без изменений. Все новые поля и эндпоинты локализованы внутри IoT Internal API.

---

## 2. Input Contract Gates Verification

Все обязательные входные handoff-блоки проверены по каноническому журналу `l4desk-service/docs/prompts/contract-handoff.md`:

| Required Handoff ID | Статус в журнале | Scope / Producer | Типы контрактов | Соответствие требованиям |
|---|---|---|---|---|
| `H-L4D-06C-MB-v1` | `ACCEPTED` | `MenuBuilder` | `API`, `DEPLOYMENT` | Gates выполнены, MenuBuilder API и финансовый контур не затрагивались. |
| `H-L4D-01C-DOCS-v1` | `ACCEPTED` | `l4desk-service` | `SPEC`, `SEQUENCE_GATE` | Agent Contract v1 сохранён, 0 коммерческих полей в IoT-слое. |
| `H-L4D-02-IOT-v1` | `ACCEPTED` | `iot-rpc-rest-app` | `API`, `EVENT`, `DEPLOYMENT` | Базовая схема сессий и событий расширена аддитивно без ломки контракта. |

---

## 3. Архитектурные разделы и нормативные инварианты

- **§3, §4 (Общая схема и топология очередей)**: IoT-сервис остаётся единственным владельцем технического состояния сессий на устройстве.
- **§5, §6 (Безопасность и модель данных)**: Защита через `Internal_Auth_dep`, валидация отсутствия коммерческих полей `validate_no_commercial_fields`, монотонный 64-битный курсор в `tb_remote_session_events`.
- **§8 (Идемпотентность и Session Lock)**:
  - Идемпотентность `POST /api/internal/v1/remote-sessions` по `operation_id`: повторный вызов с тем же `operation_id` возвращает существующую сессию без создания дубликата (HTTP 201).
  - Идемпотентность `POST /api/internal/v1/remote-sessions/{session_id}/stop` по `operation_id`: повторные вызовы возвращают статус `closed`.
  - При попытке запустить вторую сессию с другим `operation_id` возвращается HTTP 409 с телом `SessionConflictDetail`.
- **§11, §12 (Graceful Stop & Command Draining)**:
  - Командно-ориентированная остановка консольных сессий с ожиданием текущей команды до контрактного таймаута.
  - Запрет новых команд в фазе `stopping`.
- **§16, §17 (Критерии приёмки MVP)**:
  - Автоматическое вытеснение активных сессий запрещено.
  - Тарификация начинается только с `remote_session_active` и завершается `remote_session_closed`.

---

## 4. Перечень изменённых и созданных файлов

| Файл | Статус | Описание изменений |
|---|---|---|
| `app-service/core/schemas/remote_sessions.py` | Изменён | Добавлен `STARTING = "starting"` в `RemoteSessionLifecycleState`, `REMOTE_SESSION_STARTING` в `RemoteSessionEventType`, схемы `RemoteSessionStart`, `SessionConflictDetail`, `ConsoleCommandStartRequest`, `ConsoleCommandCompleteRequest`, `ConsoleCommandTimeoutRequest`, поле `timeout_sec` в `RemoteSessionStop`. |
| `app-service/core/models/remote_sessions.py` | Изменён | Добавлен частичный уникальный индекс `uq_active_remote_session_per_sn` на `tb_remote_sessions(sn)` для статусов `requested`, `starting`, `active`, `stopping`. |
| `app-service/core/services/remote_session_event_service.py` | Изменён | Реализован unified session lock, взаимное исключение (`RemoteSessionConflictError`), graceful stop с дренажем команд (`_await_console_command_or_timeout`), video teardown (`_teardown_video_session`), трекер команд (`InFlightCommand`, `start_console_command`, `complete_console_command`, `timeout_console_command`), детекция stale сессий и очистка (`is_session_stale`, `cleanup_stale_sessions`), методы переходов `start_session`, `mark_session_starting`, `mark_session_active`, `mark_session_failed`, `heartbeat`. |
| `app-service/api/internal_v1/remote_sessions.py` | Изменён | Реализована обработка `RemoteSessionConflictError` (HTTP 409), эндпоинты `POST /remote-sessions/{session_id}/start`, `POST /remote-sessions/{session_id}/heartbeat`, `POST /remote-sessions/{session_id}/commands/start`, `complete`, `timeout`. |
| `app-service/alembic/versions/2026_09_19_0006_add_remote_session_lock.py` | Создан | Миграция создания частичного уникального индекса `uq_active_remote_session_per_sn` (upgrade/downgrade). |
| `app-service/tests/core/test_alembic_migration.py` | Изменён | Добавлен тест миграции 0006 (`test_alembic_remote_session_lock_migration_upgrade_and_downgrade`). |
| `app-service/tests/core/test_l4d_07_session_lock_and_graceful_stop.py` | Создан | 11 комплексных тестов взаимного исключения, идемпотентности, crash recovery, graceful stop c bounded timeout, video stop, event ordering и REST API. |
| `docs/l4desk/contracts/schemas/iot_event_feed_openapi.json` | Изменён | Актуализированная схема OpenAPI внутреннего API. |
| `docs/l4desk/contracts/schemas/remote_session.schema.json` | Изменён | Актуализированные JSON-схемы моделей сессий. |
| `docs/l4desk/handoffs/L4D-07-IOT-report.md` | Создан | Настоящий handoff-отчёт. |

---

## 5. Результаты тестирования и доказательства

### 5.1. Полный прогон тестов
```text
pytest
====================== 396 passed, 3 warnings in 17.17s =======================
```
Все 396 тестов репозитория проходят со статусом `PASSED` (0 failed, 0 errors).

### 5.2. Тесты задачи L4D-07-IOT (`test_l4d_07_session_lock_and_graceful_stop.py`):
1. `test_mutual_exclusion_console_blocks_video_and_video_blocks_console`:
   - Запуск console-сессии блокирует попытку запуска video-сессии на том же `sn` с ошибкой `session_busy` (409 Conflict).
   - Запуск video-сессии блокирует попытку запуска console-сессии на том же `sn` с ошибкой `session_busy` (409 Conflict).
2. `test_simultaneous_concurrent_starts_mutual_exclusion`:
   - При одновременном конкурентном запуске через `asyncio.gather` ровно один запрос захватывает session lock, остальные получают стабильный conflict.
3. `test_duplicate_operations_idempotency`:
   - Повторные запросы `create_session`, `start_session`, `stop_session` с одинаковым `operation_id` идемпотентно возвращают одну и ту же сущность.
4. `test_crash_recovery_stale_session_eviction`:
   - При обнаружении зависшей сессии без heartbeat свыше таймаута она вытесняется со статусом `failed` (`stale_session_timeout`), освобождая lock новому клиенту.
5. `test_cleanup_stale_sessions_sweep`:
   - Фоновая процедура очистки корректно находит и финализирует упавшие сессии.
6. `test_start_failure_lifecycle`:
   - При сбое старта сессия переходит в `failed`, `started_at` остаётся `None` (0 тарифицируемой длительности), lock устройства освобождается.
7. `test_console_command_aware_graceful_stop_with_response`:
   - В фазе `stopping` новые команды отвергаются (`ConsoleCommandForbiddenError`), текущая команда дожидается ответа (`console_command_completed`), сессия закрывается (`remote_session_closed`).
8. `test_console_command_aware_graceful_stop_with_timeout`:
   - Если команда не успевает ответить за `timeout_sec`, срабатывает таймаут (`console_command_timed_out`), сессия закрывается без зависания.
9. `test_video_stop_control_flow`:
   - Остановка video-сессии штатно отзывает lease в `lease_registry` и переводит сессию в `closed`.
10. `test_lifecycle_transitions_ordering_and_billable_interval`:
    - Полная цепочка событий: `start_requested` → `starting` → `active` → `stop_requested` → `closed` со строго монотонными курсорами.
    - Тарифицируемый интервал строго ограничен `started_at` → `closed_at`.
11. `test_rest_api_session_lock_mutual_exclusion_and_endpoints`:
    - Проверка через HTTP-клиент FastAPI эндпоинтов создания, heartbeat, старта/завершения команд, graceful stop и 409 Conflict.

### 5.3. Регрессионные тесты контрактов:
- `test_l4d_01b_agent_contract_v1.py`: 24 passed (100% совместимость с контрактом Агента v1).
- `test_l4d_02_event_feed_full.py`: 11 passed (100% совместимость с event feed v1).
- `test_alembic_migration.py`: 5 passed (все миграции валидны).

---

## 6. Кандидатный Handoff-блок

<!-- HANDOFF:H-L4D-07-IOT-v1:BEGIN -->
```yaml
handoff_id: H-L4D-07-IOT-v1
status: ACCEPTED
contract_kinds:
  - API
  - EVENT
  - DEPLOYMENT
producer_prompt_id: L4D-07-IOT
producer_scope_project: iot-rpc-rest-app
producer_report_path: docs/l4desk/handoffs/L4D-07-IOT-report.md
producer_branch: l4desk/l4d-07-iot
producer_commit: c4e892f4c1dbf8f967109e8a06c3f63b0c9bd483
accepted_at_utc: 2026-09-19T14:30:00Z
contract_version: 1.0.0
schema_revision: 2026-09-19-v1
artifact_version: 1.0.0
previous_handoff_ids:
  - H-L4D-06C-MB-v1
  - H-L4D-01C-DOCS-v1
  - H-L4D-02-IOT-v1
consumers:
  - L4D-08A-MEDIA
  - L4D-08B-MB
  - L4D-12-MB
architecture_sections:
  - 3
  - 4
  - 5
  - 6
  - 8
  - 11
  - 12
  - 16
  - 17
artifact_paths:
  - docs/l4desk/contracts/schemas/remote_session.schema.json
  - docs/l4desk/contracts/schemas/remote_session_event.schema.json
  - docs/l4desk/contracts/schemas/iot_event_feed_openapi.json
  - app-service/alembic/versions/2026_09_19_0006_add_remote_session_lock.py
  - app-service/tests/core/test_l4d_07_session_lock_and_graceful_stop.py
artifact_sha256:
  - d72324f4a468e5b94569a6f390d122ce38364581705c90b9fb4a241b56fb68bc
  - 230a22727a493b2980ba85cb2735e50d5ac42ac9b110cf3a6f3ba03ea0ebb12b
  - 621e2ed32a7c82237a44627e2768ba15b1689b5b53ddb51ab9af48a98f08af94
  - 7de502480a352e113fa7959384b40457f70994ae721a4aa6f46840f739022b4d
  - c691b7bfdd6e3bb63c8584fb90f3a00b2df7931a2ebf9e5cdeb69e7d521053e8
compatibility:
  backward_compatible_with:
    - H-L4D-02-IOT-v1
    - H-L4D-06B-IOT-v1
    - H-L4D-06C-MB-v1
  breaking_changes: false
  notes: "Unified session lock and mutual exclusion per device (sn) for console and video remote sessions. Command-aware graceful stop with bounded timeout for console sessions and media flow teardown for video sessions. Strict lifecycle states (requested, starting, active, stopping, closed, failed) published to durable event feed 02. Agent Contract v1 protocol, MQTT topics, and payloads are 100% binary backward-compatible and untouched."
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  session_lock_enabled: true
  graceful_stop_enabled: true
contract_payload:
  session_lock:
    ownership: "iot-rpc-rest-app"
    cardinality: "exactly_one_active_or_starting_per_device_sn"
    enforcement: "uq_active_remote_session_per_sn partial index + transaction lock"
    conflict_status: 409
    conflict_code: "session_busy"
  lifecycle_states:
    - requested
    - starting
    - active
    - stopping
    - closed
    - failed
  graceful_stop:
    console: "command_aware_wait_or_timeout_new_commands_rejected"
    video: "remote_media_flow_teardown_lease_revoked"
    unbounded_wait: forbidden
  billable_interval:
    start_point: "started_at (state: active)"
    end_point: "closed_at (state: closed)"
    pre_active_billing: prohibited
  agent_contract_v1:
    topics_modified: false
    methods_modified: false
    payloads_modified: false
  alembic_revision: "0006_remote_session_lock"
  tests_passed: 396
  verification_status: VERIFIED_READY
supersedes: []
known_risks:
  - "WEB_CONCURRENCY=1 invariant required for in-memory session tracking consistency"
  - "In-flight commands without terminal response are terminated after bounded timeout_sec (default 5.0s, max 60.0s)"
consumers:
  - L4D-08A-MEDIA
  - L4D-08B-MB
  - L4D-12-MB
next_prompt_id: L4D-08A-MEDIA
```
<!-- HANDOFF:H-L4D-07-IOT-v1:END -->
