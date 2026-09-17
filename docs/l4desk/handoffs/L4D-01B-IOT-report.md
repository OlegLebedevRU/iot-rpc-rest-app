# H-L4D-01B-IOT-v1 — Отчёт о реализации provider совместимости Agent Contract v1 (`iot-rpc-rest-app`)

```yaml
handoff_id: H-L4D-01B-IOT-v1
prompt_id: L4D-01B-IOT
previous_handoff_ids:
  - H-L4D-01A-TOOLS-v1
next_prompt_id: L4D-01C-DOCS
target_repository: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
git_branch: l4desk/l4d-01b-iot
provider_version: 1.0.0
schema_revision: 2026-09-17-v1
published_agent_release: 1.7.7
supported_agent_versions:
  - 1.7.6
  - 1.7.7
created_at: 2026-09-17T21:15:00Z
architecture_sections: [3, 4, 5, 11, 12, 16, 17]
status: ACCEPTED
```

---

## 1. Executive Summary

В рамках выполнения промпта `L4D-01B-IOT` в репозитории `iot-rpc-rest-app` реализован и протестирован модуль провайдер-адаптера `AgentContractV1Adapter` (`app-service/core/adapters/agent_contract_v1.py`), обеспечивающий строгую и полную совместимость с нормативным контрактом `Agent Compatibility Contract v1` (агенты версий `1.7.6` и `1.7.7`).

Ключевые результаты шага:
1. **Contract Gate**: успешно верифицированы все 9 артефактов из входного handoff `H-L4D-01A-TOOLS-v1`, включая контрольные суммы SHA-256 схем, спецификации и исполняемых векторов `golden_vectors_v1.json`.
2. **Provider Adapter**:
   - Реализован класс `AgentContractV1Adapter` (`app-service/core/adapters/agent_contract_v1.py`), преобразующий и валидирующий сигналы между внутренней шиной платформы и агентами `l4desk`/`l4con`/`l4superv`.
   - Поддержаны неизменяемые методы `7000` (`STREAM_CONTROL`), `7001` (`EXEC_COMMAND`), `7002` (`CANCEL_TASK`) и жизненный цикл presence (`dev/{SN}/app`, `dev/{SN}/svc`).
   - Реализовано авто-приведение координат мыши (нормализация `0.0..1.0` ↔ `0..65535`).
   - Реализована дедупликация потоковых чанков `dev/{SN}/out` (`ChunkDeduplicator`) и идемпотентность завершающих ответов `dev/{SN}/res` (`CommandDeduplicator`).
3. **Изоляция коммерческих полей (Commercial Guard)**:
   - Внедрен рекурсивный инспектор `assert_no_commercial_fields`, исключающий передачу любых биллинговых, тарифных, стоимостных или организационных атрибутов (`billing`, `price`, `tariff`, `cost`, `payment`, `fee`, `amount`, `currency`, `tenant_id`, `org_id`, etc.) на сторону Агента.
4. **Сохранение существующего MQTT-клиента**:
   - Новый MQTT-клиент **не создавался**. Все взаимодействия сохранены на базе FastStream RabbitMQ/MQTT bridge и существующих топологических подписок (`q_req`, `q_ack`, `q_res`, `q_out`, `q_ctl`, `q_app`, `q_svc`).
5. **Тестирование и регрессии**:
   - Написан всесторонний набор тестов `app-service/tests/core/test_l4d_01b_agent_contract_v1.py` (24 теста), покрывающий contract gate, все 25 golden vectors (6 presence, 10 method 7000, 4 method 7001, 2 method 7002, 3 wire protocol), isolation commercial fields, duplicate chunks, unknown capabilities, error statuses и регрессионные сценарии.
   - Полный тестовый прогон репозитория: **357 passed**, 0 failed.

---

## 2. Input Contract Gate (H-L4D-01A-TOOLS-v1)

Все 9 входных артефактов сверены по содержимому и SHA-256 хэшам:

| № | Артефакт / Путь | Ожидаемый SHA-256 Digest | Фактический статус |
|---|---|---|---|
| 1 | `tools/docs/l4desk/contracts/agent_compatibility_contract_v1.json` | `38e4ae5f13d563b3ae57a83259d63f9a63049d528d9667ae33efbd5a1e71267a` | MATCH / VERIFIED |
| 2 | `tools/docs/l4desk/contracts/schemas/agent_contract_v1.schema.json` | `f065dd53101c4bf90b237c85082a05eea212e1a2b3de39d2bf890708e3a42f1d` | MATCH / VERIFIED |
| 3 | `tools/docs/l4desk/contracts/schemas/presence_event.schema.json` | `fd061b7a1a113ec4ba518208e5693ffad98593cd8096d9a013f34a0ca7748d07` | MATCH / VERIFIED |
| 4 | `tools/docs/l4desk/contracts/schemas/rpc_7000_stream_control.schema.json` | `d7ed9deaeddc4a8a5f668cd59ac95aa0941aeff083e4ef6d94a1c9e75ba4ab6e` | MATCH / VERIFIED |
| 5 | `tools/docs/l4desk/contracts/schemas/rpc_7001_exec.schema.json` | `fb511cfb368f809fb042dbece552d7f24aeedb384f7186915f82e1dfb561ee1b` | MATCH / VERIFIED |
| 6 | `tools/docs/l4desk/contracts/schemas/rpc_7002_cancel.schema.json` | `a1dac309f324b1d0e2073ac8ab251ed70f6cfd191c46ae38f3c9192854079a8f` | MATCH / VERIFIED |
| 7 | `tools/docs/l4desk/contracts/schemas/l4rtp_wire_protocol.schema.json` | `b38aeeda96a5df81561117a0acb13606b417f136abb5250e72d41d38b630bd53` | MATCH / VERIFIED |
| 8 | `tools/docs/l4desk/fixtures/golden_vectors_v1.json` | `b4f3c1a465e88babf89c0850cfd8dffc29a4cd921ec51a73e2112e6cf9c3034b` | MATCH / VERIFIED |
| 9 | `tools/tests/test_agent_compatibility_contract_v1.py` | `7e6ce52fc9351cc8a95134bcde0304fc208e0fdbec3287f279b2a7bfd0db0d52` | MATCH / VERIFIED |

---

## 3. Архитектурная инвентаризация и адаптация

### §3. Общая схема взаимодействия
- Адаптер `AgentContractV1Adapter` изолирован в слое `core/adapters/agent_contract_v1.py` и связывает низкоуровневые сообщения MQTT с сервисами `core.diagnostics` и `core.remote_input`.
- Подтверждена неизменяемость портов брокера (`8883` mTLS) и клиентских сертификатов `CN={SN}`.

### §4. Топология очередей и топиков
- Исходящие команды управления: `srv/{SN}/rsp` (RPC response) и `srv/{SN}/ctl` (низколатентный канал).
- Входящие сигналы агента:
  - `dev/{SN}/out`: потоковый вывод `l4con` (stdout/stderr chunks с `seq >= 1`, `eof`).
  - `dev/{SN}/res`: итоговый результат выполнения RPC (`7000`, `7001`, `7002`).
  - `dev/{SN}/app`: статус присутствия основного процесса (`app_online`, `app_offline`), QoS 1, retain=True.
  - `dev/{SN}/svc`: статус присутствия сервиса (`svc_online`, `svc_offline`), QoS 1, retain=True.

### §5. Безопасность и изоляция данных
- Коммерческие поля строго отсекаются при сериализации исходящих команд. Попытка передачи поля, содержащего финансовую информацию, вызывает `CommercialFieldViolationError`.
- Валидация строгости схемы: `extra="forbid"` на уровне всех Pydantic-схем запросов к агенту.

### §11. Жизненный цикл сессий и Lease Management
- Поддержаны строковые идентификаторы сессий (`sess-exec-9001`) и команд (`inv_001`, `clk_001`), при сохранении полной обратной совместимости с UUIDv4.
- `DiagnosticSessionRegistry` и `PendingCommandRegistry` обновлены для поддержки `UUID | str`.

### §12. Команды удалённого управления (7000 / 7001 / 7002)
- **7000 (Stream Control & Remote Input)**:
  - Actions: `inventory_get`, `stream_start`, `lease_renew`, `stream_stop`, `mouse_click`, `key_event`, `shortcut_action`.
  - Преобразование целочисленных экранных координат `0..65535` в нормализованные числа с плавающей точкой `0.0..1.0`.
- **7001 (Command Execution)**:
  - Shells: `cmd`, `powershell`. Неизвестные оболочки вызывают `UnknownCapabilityError`.
  - Монотонный порядок `seq >= 1` с распознаванием флага `eof=true` и exit code.
- **7002 (Cancel Task)**:
  - Корректная обработка статусов `cancelled`, `not_found`, `already_finished`.

### §16. Wire Protocol (L4RTP/1)
- Валидатор `verify_l4rtp_preamble`:
  - Преамбула 8+ байт: Magic `L4RT` (4 байта), версия `1` (1 байт), `reserved=0` (1 байт), длина SN (uint16-BE), ASCII SN.
- Валидатор `verify_l4rtp_frame_header`:
  - Заголовок 4 байта (8 hex-символов): Канал (1=RTP, 2=RTCP), `reserved=0`, длина полезной нагрузки (uint16-BE).

### §17. Развёртывание и надёжность
- Единый воркер FastAPI/FastStream (`WEB_CONCURRENCY=1`).
- Поддержка дедупликации чанков при повторной доставке MQTT QoS 1.

---

## 4. Результаты тестов и регрессий

### 4.1. Сводка тестов
- `app-service/tests/core/test_l4d_01b_agent_contract_v1.py`: **24 passed**
- Полный набор тестов проекта: **357 passed**, 0 failed, 3 warnings.

### 4.2. Устранённые регрессии (Regression Tests)
1. **Строковые идентификаторы сессий (`session_id`)**:
   - *Было*: `session_id: UUID` в схемах `DeviceOutputEnvelope` и `DiagnosticSession` приводило к ошибке валидации при поступлении контрактных строк вида `sess-exec-9001`.
   - *Исправлено*: тип расширен до `UUID | str` с валидатором `_parse_session_id`, который сохраняет строковые ID и автоматически конвертирует валидные UUID-строки в `UUID`.
2. **Финальные чанки потока без явных полей `kind` и `stream`**:
   - *Было*: контрактный EOF-чанк `{session_id, seq, data: "", eof: true, exit_code: 0}` отклонялся `DeviceOutputEnvelope` из-за `extra="forbid"` и отсутствия полей `kind` и `stream`.
   - *Исправлено*: добавлен `model_validator(mode="before")` `_adapt_contract_v1`, автоматически назначающий `kind=OutputKind.RESULT` и `stream="stdout"` при наличии `eof=True` и `exit_code`.

---

## 5. Deployment & Production-compatible Contract Smoke

В соответствии с регламентом `docs/manual-app1-deploy-runbook.md`:
- **Целевой хост**: `etranprocessing` (`user1@87.242.100.34`, ключ `d:\.ssh\id_ed25519`).
- **Стенд**: Production VM.
- **Инфраструктурная изоляция**: Сервисы `rabbitmq`, `nginx`, `pg` не затрагивались.
- **Smoke-проверка**:
  - Чтение и верификация golden vectors на целевом окружении.
  - Проверка ответа `/health` и OpenAPI schema.
  - Проверка корректной маршрутизации топиков `dev/{SN}/out` и `dev/{SN}/res`.

---

## 6. Rollback-инструкция

В случае необходимости отката:
1. Переключить репозиторий на предыдущий стабильный коммит `2488395` (или `de431c1`):
   ```bash
   git checkout 2488395
   ```
2. Пересобрать контейнер `app1`:
   ```bash
   docker compose build app1
   docker compose up -d --no-deps app1
   ```
3. Проверить статус контейнера:
   ```bash
   docker compose ps app1
   docker compose logs --tail=50 app1
   ```

---

## 7. Candidate-блок для handoff-журнала

<!-- HANDOFF:H-L4D-01B-IOT-v1:BEGIN -->
```yaml
handoff_id: H-L4D-01B-IOT-v1
status: ACCEPTED
contract_kinds:
  - DEPLOYMENT
  - FIXTURES
producer_prompt_id: L4D-01B-IOT
producer_scope_project: iot-rpc-rest-app
producer_report_path: docs/l4desk/handoffs/L4D-01B-IOT-report.md
producer_branch: l4desk/l4d-01b-iot
producer_commit: 0307dd7953b339ee48c3068a490732c82ea4e401
accepted_at_utc: 2026-09-17T21:15:00Z
contract_version: 1.0.0
schema_revision: 2026-09-17-v1
artifact_version: 1.7.7
artifact_paths:
  - app-service/core/adapters/agent_contract_v1.py
  - app-service/tests/core/test_l4d_01b_agent_contract_v1.py
artifact_sha256:
  - 4c22174762d570dd70cbcbea28fc419748184a9a65ae9296f3f7577d7fa584e8
  - 0c5005d42935736030c793af7b4e3c9e08ba382523750d742d5a2d169e768a7f
compatibility:
  backward_compatible_with:
    - 0.2.1
  breaking_changes: false
  notes: Provider adapter AgentContractV1Adapter strictly implements Agent Compatibility Contract v1 (agents 1.7.6, 1.7.7) without modifying agent topics, method codes or required payloads. Zero commercial fields transmitted to Agent. Full backward compatibility with existing IoT platform baseline 0.2.1 preserved.
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  agent_contract_v1_adapter: enabled
  commercial_guard: enabled
contract_payload:
  identifiers:
    sn_pattern: "^[0-9A-Za-z_-]{6,32}$"
    cert_dn_pattern: "CN={SN}"
    task_id_pattern: "^task-[a-z0-9-]+$"
    session_id_pattern: "^sess-[a-z0-9-]+$"
    command_id_pattern: "^[a-z0-9_-]+$"
  operations_events:
    presence_topics:
      - "dev/{SN}/app"
      - "dev/{SN}/svc"
    rpc_topics:
      - "srv/{SN}/tsk"
      - "srv/{SN}/rsp"
      - "srv/{SN}/ctl"
      - "dev/{SN}/out"
      - "dev/{SN}/res"
      - "dev/{SN}/ctl"
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
    validation_errors: ["commercial_field_detected", "invalid_qos", "invalid_retain", "unknown_capability"]
  invariants:
    - "Zero commercial, billing, price, fee, tariff, cost, or organization fields transmitted to Agent"
    - "No new MQTT client created; existing FastStream topology and subscriptions preserved"
    - "Presence messages require QoS 1 and retain=true"
    - "Streaming output chunks over dev/{SN}/out have monotonic sequence numbering and boolean eof"
    - "Mouse coordinates automatically normalized between 0.0..1.0 and 0..65535"
    - "Duplicate streaming chunks and completion responses deduplicated idempotently"
supersedes:
  - H-L4D-00B-IOT-v1
known_risks:
  - "In-memory session registry requires WEB_CONCURRENCY=1 until distributed Redis storage is added"
  - "Interactive mouse/key input injection is rejected if screen is locked or session unavailable"
consumers:
  - L4D-01C-DOCS
next_prompt_id: L4D-01C-DOCS
```
<!-- HANDOFF:H-L4D-01B-IOT-v1:END -->
