# H-L4D-06B-IOT-v1 — Отчёт о реализации Versioned Idempotent Device Provisioning Contract (`iot-rpc-rest-app`)

```yaml
handoff_id: H-L4D-06B-IOT-v1
prompt_id: L4D-06B-IOT
previous_handoff_ids:
  - H-L4D-06A-PB-v1
  - H-L4D-02-IOT-v1
output_handoff_id: H-L4D-06B-IOT-v1
next_prompt_id: L4D-06C-MB
target_repository: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
git_branch: l4desk/l4d-06b-iot
contract_version: 1.0.0
schema_revision: 2026-09-18-v1
created_at: 2026-09-18T19:40:00Z
architecture_sections: [3, 4, 5, 6, 11, 12, 14, 16, 17]
status: ACCEPTED
```

---

## 1. Executive Summary

В рамках выполнения задачи `L4D-06B-IOT` в сервисе `iot-rpc-rest-app` реализован версионированный идемпотентный контракт сервисного provisioning устройств и терминалов (`POST /api/internal/v1/devices/provision` и сопутствующие запросы статуса `GET /api/internal/v1/devices/provision/by-operation/{operation_id}`), а также публикация устойчивых фактов подготовки устройства в принятый журнал событий (`tb_remote_session_events` feed).

Ключевые результаты реализации:
1. **Contract Gates Passed**:
   - Входной handoff `H-L4D-06A-PB-v1`: зафиксированы точные идентификаторы (`tenant_id: int`, `terminal_id: int`, `sn: str`, `operation_id: str`, `correlation_id: str | None`) и семантика идемпотентности (`replayed_flag: bool`, конфликт при мутации параметров). Прямой вызов `ProcessingBackend` из `iot-rpc-rest-app` не производится (в соответствии с границами владения архитектуры).
   - Входной handoff `H-L4D-02-IOT-v1`: использован принятый event envelope (`cursor: BIGSERIAL`, `event_id`, `sn`, `tenant_id`, `terminal_id`, `device_id`, `operation_id`, `correlation_id`, `lifecycle_state`, `reason`, `payload`).
2. **Endpoint & Idempotency Semantics**:
   - Реализован маршрут `POST /api/internal/v1/devices/provision` (и `GET /api/internal/v1/devices/provision/by-operation/{operation_id}`, `GET /api/internal/v1/devices/provision/by-sn/{sn}`).
   - При первом вызове создаётся запись операции, сущности ядра (`Org`, `Device`, `DeviceOrgBind`, `DeviceConnection`, `DeviceAuditLog`), эмитируется факт `device_provisioned` и возвращается HTTP 201 Created (`replayed_flag=False`, `status="provisioned"`).
   - При повторном вызове с идентичным `operation_id` и тем же payload возвращается тот же ресурс с HTTP 200 OK (`replayed_flag=True`).
   - При попытке повторного использования `operation_id` с изменёнными параметрами (другой `terminal_id`, `sn`, `tenant_id` или `device_id`) возвращается HTTP 409 Conflict (`OPERATION_ID_CONFLICT`).
3. **Устойчивое отображение (Stable Device ID / SN Mapping) & Identity Conflict Guard**:
   - За каждым физическим устройством (`sn`) устойчиво закрепляется выделенный числовой идентификатор `device_id` и принадлежность к тенанту (`tenant_id`).
   - Попытка привязать существующий серийный номер `sn` к другому тенанту блокируется с HTTP 409 Conflict (`IDENTITY_CONFLICT`).
   - Попытка перепривязать `terminal_id` внутри тенанта к другому `sn` блокируется с HTTP 409 Conflict (`IDENTITY_CONFLICT`).
   - Конфликты явного `device_id` с другим устройством блокируются с HTTP 409 Conflict (`IDENTITY_CONFLICT`).
4. **Durable Facts in Accepted Event Feed**:
   - Факты provisioning публикуются через принятый долговечный event feed (`tb_remote_session_events`).
   - Типы событий расширены аддитивно: `device_provision_requested`, `device_provisioned`, `device_provision_failed`.
   - Запрет коммерческих терминов (`validate_no_commercial_fields`) гарантирует изоляцию IoT-контура от биллинговых терминов.
   - Протокол Агента не изменялся, отдельный MQTT-клиент не создавался.
5. **Persistence & Database Migration**:
   - Создана таблица `tb_device_provisionings` для сохранения состояния операций provisioning (`operation_id`, `contract_version`, `tenant_id`, `terminal_id`, `sn`, `device_id`, `status`, `correlation_id`, `payload_hash`, `provisioning_metadata`, таймстемпы).
   - Подготовлена и верифицирована миграция Alembic: `2026_09_18_0005_add_device_provisioning_operations.py`.
6. **Тестирование**:
   - Написан всесторонний набор тестов `test_l4d_06b_device_provisioning_contract.py` (duplicate/idempotency replay, concurrent race handling, identity conflicts, tenant isolation, restart persistence, event emission, auth/error schemas, artifacts generation and verification).
   - Все 382 теста проекта успешно проходят.

---

## 2. Input Contract Gates

| Parameter | Gate 1 (`H-L4D-06A-PB-v1`) | Gate 2 (`H-L4D-02-IOT-v1`) | Status |
|---|---|---|---|
| **Handoff Status** | `ACCEPTED` | `ACCEPTED` | Verified |
| **Consumers** | `L4D-06B-IOT`, `L4D-06C-MB` | `L4D-03-MB`, `L4D-06B-IOT`, `ALL_FOLLOWING` | Verified |
| **Exact Identifiers** | `tenant_id: int`, `terminal_id: int`, `sn: str`, `operation_id: str`, `correlation_id: str \| None` | `cursor: BIGSERIAL`, `event_id_pattern`, `operation_id_pattern`, `sn_pattern` | Verified & Applied |
| **Idempotency Rule** | `replayed_flag: bool`, conflict on parameter change | Deduplication by `event_id` / `operation_id` without cursor progression | Verified & Applied |
| **Commercial Guard** | N/A | `validate_no_commercial_fields` | Enforced |
| **Broker/Agent Impact** | No direct changes | Zero agent protocol mutations, no extra MQTT client | Invariant strictly preserved |

---

## 3. Архитектурная реализация и инварианты

### §3, §4, §5. Архитектурные границы и владение данными
- `iot-rpc-rest-app` является владельцем runtime-записи устройства (`tb_devices`, `tb_device_connections`, `tb_device_org_binds`) и технических фактов.
- Бизнес-запись терминала и тарификация принадлежат `MenuBuilder` (consumer `L4D-06C-MB`), выпуск сертификатов — `ProcessingBackend`. `iot-rpc-rest-app` не осуществляет непрямых вызовов соседних баз данных или сервисов без контракта.
- Взаимодействие осуществляется через защищённый внутренний REST API:
  - Авторизация: `Internal_Auth_dep` (`X-Internal-Service-Key` или `Authorization: Bearer <secret>`).

### §6. Контракт Provisioning
- **URL**: `POST /api/internal/v1/devices/provision`
  - Запрос: `DeviceProvisionRequest` (`operation_id`, `contract_version`, `tenant_id`, `terminal_id`, `sn`, опциональный `device_id`, `correlation_id`, `requested_by_user_id`, `metadata`).
  - Ответ: `DeviceProvisionResponse` (`operation_id`, `status` [requested, provisioned, failed], `tenant_id`, `terminal_id`, `device_id`, `sn`, `contract_version`, `correlation_id`, `replayed_flag`, `created_at`, `provisioned_at`, `error_code`, `error_message`).
- **Idempotency**:
  - Хэш параметров `compute_provision_payload_hash` вычисляется по каноническому JSON запроса (`tenant_id`, `terminal_id`, `sn`, `device_id`, `requested_by_user_id`, `metadata`).
  - Повтор с тем же `operation_id` и совпадающим хэшем возвращает HTTP 200 OK (`replayed_flag=True`).
  - Повтор с тем же `operation_id` и несовпадающим хэшем возвращает HTTP 409 Conflict (`OPERATION_ID_CONFLICT`).
- **Query Endpoints**:
  - `GET /api/internal/v1/devices/provision/by-operation/{operation_id}`: получение состояния по `operation_id`.
  - `GET /api/internal/v1/devices/provision/by-sn/{sn}`: получение последнего состояния устройства по `sn`.
  - `GET /api/internal/v1/devices/provision/{operation_id}`: алиас прямого пути.

### §11, §12. Stable Device ID / SN Mapping & Invariants
- При первой регистрации `sn` сервис атомарно выделяет монотонный числовой `device_id` и синхронизирует:
  1. `tb_orgs`: гарантирует существование тенанта.
  2. `tb_devices`: создает/активирует устройство с уникальным `sn` и `device_id`.
  3. `tb_device_org_binds`: закрепляет устройство за тенантом.
  4. `tb_device_connections`: объявляет `client_id=sn`.
  5. `tb_device_audit_logs`: фиксирует событие аудита `PROVISIONED`.
  6. `tb_device_provisionings`: сохраняет запись операции со статусом `provisioned`.
  7. `tb_remote_session_events`: публикует событие `device_provisioned` в курсорный event feed.
- Cross-tenant hijacking: попытка тенанта B зарегистрировать `sn`, принадлежащий тенанту A, немедленно отклоняется с HTTP 409 Conflict (`IDENTITY_CONFLICT`).

### §14. Безопасность и аудит
- Все запросы требуют валидный сервисный ключ (`Internal_Auth_dep`).
- Ошибки возвращаются в унифицированном формате `DeviceProvisionErrorResponse` (`detail: {error_code, message, operation_id, timestamp}`).
- Метаданные валидируются через `validate_no_commercial_fields`: финансовые термины запрещены.

---

## 4. Результаты тестов

Полный локальный прогон unit- и контрактных тестов проекта:
```text
pytest
====================== 382 passed, 3 warnings in 19.22s =======================
```

Проверенные тестовые сценарии в `test_l4d_06b_device_provisioning_contract.py`:
1. `test_duplicate_request_idempotency_flow`:
   - Первый запрос: HTTP 201 Created (`replayed_flag=False`, `status="provisioned"`).
   - Повторный идентичный запрос: HTTP 200 OK (`replayed_flag=True`, неизменные attributes/timestamps).
   - Запросы статуса по `operation_id` и `sn`: HTTP 200 OK.
2. `test_reused_operation_id_different_payload_conflict`:
   - Мутация `terminal_id`, `tenant_id` или `sn` при том же `operation_id` возвращает HTTP 409 Conflict (`OPERATION_ID_CONFLICT`).
3. `test_identity_conflicts`:
   - Попытка перехвата `sn` чужим тенантом: HTTP 409 Conflict (`IDENTITY_CONFLICT`).
   - Попытка зарегистрировать тот же `terminal_id` с другим `sn`: HTTP 409 Conflict (`IDENTITY_CONFLICT`).
   - Конфликт `device_id` с другим устройством: HTTP 409 Conflict (`IDENTITY_CONFLICT`).
4. `test_tenant_isolation`:
   - Тенанты 100 и 200 изолированно владеют одинаковыми номерами `terminal_id` (например, 1) с независимыми `device_id` и `sn`.
5. `test_concurrent_requests_handling`:
   - 5 одновременных параллельных запросов с одинаковым `operation_id` успешно обрабатываются без необработанных исключений целостности БД, ровно один создает ресурс (201), остальные возвращают replay (200).
6. `test_restart_persistence_and_replay`:
   - Данные, зафиксированные в БД, сохраняются при перезапуске сервиса; повторный запрос после перезапуска возвращает HTTP 200 OK (`replayed_flag=True`).
7. `test_event_emission_and_feed_integration`:
   - Проверено создание события `device_provisioned` в `tb_remote_session_events` с монотонным курсором, статусом `provisioned` и отсутствием финансовых полей.
8. `test_auth_and_error_schema`:
   - Запросы без авторизации и с неверным ключом возвращают HTTP 403 Forbidden.
   - Валидный `Bearer` токен успешно авторизует запрос (HTTP 201).
   - Невалидный `sn` или коммерческие термины в `metadata` отклоняются (HTTP 422).
   - Несуществующий `operation_id` возвращает HTTP 404 Not Found (`OPERATION_NOT_FOUND`).
9. `test_generate_and_verify_contract_artifacts`:
   - Проверена генерация и соответствие схем OpenAPI, JSON Schema и golden fixtures.

---

## 5. Опубликованные артефакты и контрольные суммы

| Artifact Path | Format / Kind | Description | SHA-256 Digest |
|---|---|---|---|
| `docs/l4desk/contracts/schemas/device_provisioning_openapi.json` | OpenAPI 3.1.0 | Полная OpenAPI-спецификация сервисного контракта provisioning | `dccc1beefc97be7b4d89502193cb865e95f7fe3b4a3bbae8d528574c7d736a3d` |
| `docs/l4desk/contracts/schemas/device_provision_request.schema.json` | JSON Schema Draft 2020-12 | Схема запроса `DeviceProvisionRequest` | `3cba891ebef0e1783bda8bdf02821e3eb6f9a12eba080b31a735fb2c5a667081` |
| `docs/l4desk/contracts/schemas/device_provision_response.schema.json` | JSON Schema Draft 2020-12 | Схема ответа `DeviceProvisionResponse` | `0f2914e286fbe665401dc412acb4308aa91741c5f6d3a141acd301e1bf1cf3a8` |
| `docs/l4desk/fixtures/device_provisioning_examples_v1.json` | Golden JSON Fixtures | Эталонные примеры запросов, ответов 201/200, ошибок 409/403 и событий feed | `86dd26818fadf2d8c4ea07113a77410f19f3cbbf64fb6eccc098100bf893c2fb` |

---

## 6. Регламент развёртывания и эксплуатационные проверки

В соответствии с регламентом `docs/manual-app1-deploy-runbook.md` и политикой каскада:
1. Применение миграций базы данных:
   ```bash
   uv run alembic upgrade head
   ```
2. Сборка и перезапуск исключительно контейнера приложения `app1` (без пересоздания базы данных `pg`, брокера `rabbitmq`, `nginx`, `nginx-mutual`):
   ```bash
   docker compose build app1
   docker compose up -d --no-deps app1
   ```
3. Проверка статуса и логов:
   ```bash
   docker compose ps app1
   docker compose logs --tail=100 app1
   ```
4. Smoke-проверка доступности и авторизации эндпоинта:
   - Проверка отсечения неавторизованного запроса:
     ```bash
     curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/api/internal/v1/devices/provision
     # Ожидается: 403
     ```
   - Проверка запроса несуществующей операции:
     ```bash
     curl -s -X GET http://localhost:8000/api/internal/v1/devices/provision/by-operation/018f3a5b-0000-0000-0000-000000000000 \
          -H "X-Internal-Service-Key: <configured_key>"
     # Ожидается: 404 {"detail":{"error_code":"OPERATION_NOT_FOUND",...}}
     ```

---

## 7. План отката (Rollback Readiness)

1. Откат миграции базы данных:
   ```bash
   uv run alembic downgrade 0004_remote_session_events
   ```
2. Переключение на коммит до ветки `l4desk/l4d-06b-iot`:
   ```bash
   git checkout l4desk/l4d-02-iot
   ```
3. Пересборка и перезапуск контейнера `app1`:
   ```bash
   docker compose build app1 && docker compose up -d --no-deps app1
   ```

---

## 8. Candidate-блок для handoff-журнала

<!-- HANDOFF:H-L4D-06B-IOT-v1:BEGIN -->
```yaml
handoff_id: H-L4D-06B-IOT-v1
status: ACCEPTED
contract_kinds:
  - API
  - EVENT
  - DEPLOYMENT
producer_prompt_id: L4D-06B-IOT
producer_scope_project: iot-rpc-rest-app
producer_report_path: docs/l4desk/handoffs/L4D-06B-IOT-report.md
producer_branch: l4desk/l4d-06b-iot
producer_commit: HEAD
accepted_at_utc: 2026-09-18T19:40:00Z
contract_version: 1.0.0
schema_revision: 2026-09-18-v1
artifact_version: 1.0.0
artifact_paths:
  - docs/l4desk/contracts/schemas/device_provisioning_openapi.json
  - docs/l4desk/contracts/schemas/device_provision_request.schema.json
  - docs/l4desk/contracts/schemas/device_provision_response.schema.json
  - docs/l4desk/fixtures/device_provisioning_examples_v1.json
artifact_sha256:
  - dccc1beefc97be7b4d89502193cb865e95f7fe3b4a3bbae8d528574c7d736a3d
  - 3cba891ebef0e1783bda8bdf02821e3eb6f9a12eba080b31a735fb2c5a667081
  - 0f2914e286fbe665401dc412acb4308aa91741c5f6d3a141acd301e1bf1cf3a8
  - 86dd26818fadf2d8c4ea07113a77410f19f3cbbf64fb6eccc098100bf893c2fb
compatibility:
  backward_compatible_with:
    - H-L4D-06A-PB-v1
    - H-L4D-02-IOT-v1
  breaking_changes: false
  notes: "Versioned idempotent device and terminal provisioning contract implemented in iot-rpc-rest-app (/api/internal/v1/devices/provision). Supports exact identifier mapping (tenant_id: int, terminal_id: int, sn: str, operation_id: str, correlation_id: str | None), status states (requested, provisioned, failed), stable device_id/SN allocation, identity/tenant conflict protection (409 Conflict), and fact publishing into the durable tb_remote_session_events feed. Agent protocol and broker topologies remain 100% binary backward-compatible."
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  device_provisioning_v1: enabled
contract_payload:
  identifiers:
    tenant_id: int
    terminal_id: int
    sn: str
    device_id: int
    operation_id: str
    correlation_id: str | None
  states:
    - requested
    - provisioned
    - failed
  endpoints:
    - method: POST
      path: /api/internal/v1/devices/provision
      auth: require_service_auth
      request_schema: DeviceProvisionRequest
      response_schema: DeviceProvisionResponse
      status_codes:
        201: Created (new device provisioned, replayed_flag=false)
        200: OK (idempotent replay of existing operation_id, replayed_flag=true)
        400: Bad Request (INVALID_PAYLOAD)
        401: Unauthorized (SERVICE_AUTH_FAILED)
        403: Forbidden (INVALID_CREDENTIALS)
        409: Conflict (OPERATION_ID_CONFLICT / IDENTITY_CONFLICT)
        422: Unprocessable Entity (validation error)
    - method: GET
      path: /api/internal/v1/devices/provision/by-operation/{operation_id}
      auth: require_service_auth
      response_schema: DeviceProvisionResponse
      status_codes:
        200: OK
        401: Unauthorized
        403: Forbidden
        404: Not Found (OPERATION_NOT_FOUND)
    - method: GET
      path: /api/internal/v1/devices/provision/by-sn/{sn}
      auth: require_service_auth
      response_schema: DeviceProvisionResponse
      status_codes:
        200: OK
        401: Unauthorized
        403: Forbidden
        404: Not Found (DEVICE_NOT_FOUND)
  events:
    - "device_provision_requested"
    - "device_provisioned"
    - "device_provision_failed"
  idempotency_semantics:
    replayed_flag: boolean
    conflict_on_parameter_change: true
    cross_tenant_sn_protection: enforced
    terminal_rebind_protection: enforced
supersedes: []
known_risks: []
consumers:
  - L4D-06C-MB
next_prompt_id: L4D-06C-MB
```
<!-- HANDOFF:H-L4D-06B-IOT-v1:END -->
