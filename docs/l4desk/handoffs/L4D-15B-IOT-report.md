# H-L4D-15B-IOT-v1 — Отчёт о реализации архивации IoT/RPC подробностей (`iot-rpc-rest-app`)

```yaml
handoff_id: H-L4D-15B-IOT-v1
prompt_id: L4D-15B-IOT
prompt_type: archive-implementation
target_repository: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
git_branch: l4desk/l4d-15b-iot
producer_commit: af3b4f06456ddad2c8c44477dc52f25c49ee5722
contract_version: 1.0.0
schema_revision: 1.0.0
contract_kinds:
  - API
  - EVENT
  - DEPLOYMENT
required_handoff_ids:
  - H-L4D-15A-DOCS-v1
  - H-L4D-02-IOT-v1
  - H-L4D-07-IOT-v1
consumers:
  - L4D-15C-MEDIA
  - L4D-16-MB
next_prompt_id: L4D-15C-MEDIA
architecture_sections: [3, 5, 6, 8, 11, 12, 14, 15, 16, 17]
created_at: 2026-09-21T03:30:00Z
status: ACCEPTED
```

---

## 1. Executive Summary

В рамках задачи `L4D-15B-IOT` в сервисе `iot-rpc-rest-app` реализована помесячная архивация массовых технических данных устройств, RPC-переходов и событий сессий в строгом соответствии с контрактом `Archive Manifest Contract v1` (`H-L4D-15A-DOCS-v1`).

### Ключевые результаты реализации:
1. **Классификация данных и No-Financial-Purge Invariant**:
   - Локально принадлежащие high-volume технические данные классифицированы на 3 типа записей:
     - `iot_session_events` — детальные события удаленных сессий из `tb_remote_session_events` со сквозным полем `cursor`.
     - `rpc_transitions` — завершенные задачи управления устройствами из `tb_dev_tasks`.
     - `presence_events` — технические события присутствия и подключения устройств из `tb_dev_events`.
   - **No-Financial-Purge**: Сводные строки сессий (`tb_remote_sessions`), устройства, ключи доступа, биллинг и конфигурации категорически исключены из процедур удаления (Purge).
2. **Детерминированный формат и сериализация**:
   - Данные экспортируются в потоковый детерминированный `JSONL.gz` (UTF-8, без BOM, LF, ключи отсортированы, компактные разделители `,` и `:`, `mtime=0.0` в заголовке gzip).
   - Вычисляется побайтный потоковый SHA-256 и формируется файл контрольной суммы `checksum.sha256` в стандартном формате sha256sum (`<hash>  data.jsonl.gz\n`).
   - Производится обязательное маскирование чувствительных данных (`password`, `secret`, `token`, `key`, `auth`, `pin`, `jwt` и т.д.) через `SecretScrubber`.
3. **Безопасность путей и хранилища (PathSecurityGuard)**:
   - Конфигурируемая точка монтирования архивов (`APP_CONFIG__ARCHIVE__VOLUME_ROOT`, по умолчанию `/mnt/l4desk-archive`).
   - Защита от path traversal (`..`, `\0`), запрет символических ссылок (`is_symlink`), строгая валидация относительного пути внутри корня тома.
   - Проверка свободного места на диске (`min_free_disk_bytes`, порог 100 MB) перед началом операций.
4. **Многоуровневые барьеры верификации (Guards)**:
   - **RetentionGuard**: строгая проверка закрытого месяца. Разрешены только месяцы, строго старшие 3 полных закрытых календарных месяцев относительно даты выполнения (`diff_months >= 4`). В сентябре 2026 года разрешены месяцы до мая 2026 включительно.
   - **ActiveRecordsGuard**: проверка отсутствия незавершенных/активных/переоткрытых сессий (`status IN ('requested', 'starting', 'active', 'stopping')` или `closed_at IS NULL`) в целевом месяце.
   - **CursorGuard**: обязательная проверка продвижения курсора потребителей (`consumers_passed_cursor >= through_cursor`). При отставании биллингового курсора MenuBuilder очистка блокируется с кодом `CURSOR_LAG_DETECTED`.
   - **Verification & Restore Sample**: полное контрольное перечитывание файла с диска, сверка количества записей и хеша SHA-256, десериализация и валидация схемы первых N записей выборки (`sample_restore_size`).
5. **Атомарность и порционная очистка (Bounded Chunked Purge)**:
   - Экспорт производится в staging-каталог `.tmp_<batch_id>_<timestamp>` на том же томе.
   - Атомарное продвижение через `os.replace` в постоянный путь `<volume_root>/<YYYY>/<MM>/iot-rpc-rest-app/<batch_id>/` только после успешного завершения всех проверок верификации.
   - Порционное удаление архивных данных из оперативных таблиц батчами (`chunk_size`, по умолчанию 1000 строк) с промежуточным сбросом транзакций.
6. **Управление и развертывание**:
   - Фоновый воркер по умолчанию отключен (`APP_CONFIG__ARCHIVE__ENABLED=false`).
   - Реализован CLI инструмент `run_archive_worker.py` с поддержкой `--dry-run`, `--force`, `--purge / --no-purge` и безопасного перезапуска после сбоев.
   - Реализован внутренний REST API: `POST /api/internal/v1/archive/run`, `GET /batches`, `GET /batches/{id}`, `GET /batches/{id}/manifest`.

---

## 2. Input Contract Gates Verification

Все обязательные входные handoff-блоки проверены по каноническому журналу `l4desk-service/docs/prompts/contract-handoff.md`:

| Required Handoff ID | Статус в журнале | Scope / Producer | Типы контрактов | Соответствие требованиям |
|---|---|---|---|---|
| `H-L4D-15A-DOCS-v1` | `ACCEPTED` | `l4desk-service` | `SCHEMA`, `FIXTURES` | Все 7 контрольных сумм артефактов проверены (100% match), 13 acceptance vector тестов пройдены без ошибок. |
| `H-L4D-02-IOT-v1` | `ACCEPTED` | `iot-rpc-rest-app` | `API`, `EVENT`, `DEPLOYMENT` | Сквозной курсор `tb_remote_session_events` сохранён и используется в `cursor_bounds`. |
| `H-L4D-07-IOT-v1` | `ACCEPTED` | `iot-rpc-rest-app` | `API`, `EVENT`, `DEPLOYMENT` | Session lock и статусы сессий строго соблюдаются в ActiveRecordsGuard. |

### Проверка контрольных сумм артефактов H-L4D-15A-DOCS-v1:
- `archive-manifest.schema.json`: `fc945431d6ceef34511fa40aea379588deb802a44a302061db102970c3d301fb` — ВЕРНО
- `schemas.json`: `b769d3c45e4819e46d4d7455edd055e03fcf4388f6d2f23089d79c810961d55c` — ВЕРНО
- `examples.json`: `a43a07a176dfa28b450dfa5fb456a0451028f95568f0852615168a863245cde2` — ВЕРНО
- `contract.md`: `71572b916c893c09cc0a11c662f826947f8470eed5b0743ffb86cfebecbc09f6` — ВЕРНО
- `validate_archive_manifest.py`: `d9953d93a3fe1f3d635825802c6054cfbca51e2f1b12b0059b2929cc25a77b6b` — ВЕРНО
- `verification.md`: `e27d848f8226415f216a3627a6b63636f5bd92729eddd471a54b2fd92fafa905` — ВЕРНО
- `L4D-15A-DOCS-report.md`: `3aa7dfdd4e40f6c92f58174e4e5d708e7f25c2ca246f405b9100d320aecde8c1` — ВЕРНО

---

## 3. Архитектурные разделы и нормативные инварианты

- **§3 (Общая архитектура и владение)**: `iot-rpc-rest-app` владеет архивацией локальных технических событий (`iot_session_events`, `rpc_transitions`, `presence_events`).
- **§5, §6 (Безопасность и модель данных)**: Таблица реестра пакетов `fin_archive_batches` с составным первичным ключом `(id, source_project)`.
- **§8 (Идемпотентность и восстановление)**: Идемпотентный перезапуск цикла. При падении до атомарного переименования незавершенный staging безопасно очищается. Повторный запуск для `purged` батча возвращает готовый манифест без дублирования или повторного удаления.
- **§11, §12 (Жизненный цикл сессий и Active Records Guard)**: Запрет архивации и очистки при наличии открытых сессий в целевом месяце.
- **§14, §15 (Инвариант No-Financial-Purge и Cursor Guard)**: Очистка технических данных разрешается только если обязательный потребитель суточного биллинга (`MenuBuilder`) подтвердил продвижение курсора (`consumers_passed_cursor >= through_cursor`). Сводная таблица `tb_remote_sessions` никогда не очищается.
- **§16, §17 (Критерии приёмки и границы хранения)**: Правило «строго старше 3 закрытых календарных месяцев» гарантирует неприкосновенность оперативного окна расчётов и сверок. Срок архивного хранения установлен в 3 года.

---

## 4. Перечень созданных и изменённых файлов

| Файл | Статус | Описание |
|---|---|---|
| `app-service/core/archive/__init__.py` | Создан | Экспорт публичного API модуля архивации. |
| `app-service/core/archive/canonical.py` | Создан | Детерминированная сериализация, secret scrubbing, потоковый sha256, gzip mtime=0, валидация manifest.json. |
| `app-service/core/archive/guards.py` | Создан | Защитные барьеры: RetentionGuard, ActiveRecordsGuard, CursorGuard, PathSecurityGuard. |
| `app-service/core/archive/exceptions.py` | Создан | Типизированные исключения со стандартными кодами ошибок контракта. |
| `app-service/core/archive/exporter.py` | Создан | Выгрузка записей трех категорий, детерминированная сортировка, экспорт в staging. |
| `app-service/core/archive/verifier.py` | Создан | Полное контрольное перечитывание, сверка хешей, sample restore, cursor guard, атомарное переименование `os.replace`. |
| `app-service/core/archive/purger.py` | Создан | Безопасная порционная очистка таблиц деталей с соблюдением No-Financial-Purge. |
| `app-service/core/archive/pipeline.py` | Создан | Оркестратор жизненного цикла, идемпотентное возобновление и обработка сбоев. |
| `app-service/core/models/archive.py` | Создан | Модель `FinArchiveBatch` таблицы `fin_archive_batches`. |
| `app-service/core/models/__init__.py` | Изменён | Регистрация модели `FinArchiveBatch`. |
| `app-service/core/schemas/archive.py` | Создан | Pydantic схемы запросов и ответов REST API архивации. |
| `app-service/api/internal_v1/archive.py` | Создан | Внутренний REST контроллер архивации (`/api/internal/v1/archive`). |
| `app-service/api/internal_v1/__init__.py` | Изменён | Подключение роутера архивации в общий internal_v1 router. |
| `app-service/core/config.py` | Изменён | Добавлен `ArchiveConfig` (`enabled=False`, `volume_root`, `retention_years=3`, `chunk_size=1000`). |
| `app-service/alembic/versions/2026_09_21_0007_add_fin_archive_batches.py` | Создан | Миграция Alembic для таблицы `fin_archive_batches`. |
| `app-service/scripts/run_archive_worker.py` | Создан | CLI инструмент запуска архивации с поддержкой `--dry-run`, `--force`, `--purge`. |
| `app-service/tests/core/test_l4d_15b_archive.py` | Создан | 9 комплексных тестов архивного конвейера, guards, deterministic gzip, crash at every phase, bounded purge. |
| `app-service/tests/api/v1/test_internal_v1_archive_api.py` | Создан | Тесты REST API эндпоинтов архивации. |
| `docs/l4desk/handoffs/L4D-15B-IOT-report.md` | Создан | Настоящий handoff-отчёт. |

---

## 5. Доказательства верификации и тестирования

### 1. Результаты выполнения pytest:
```text
collected 406 items
406 passed, 3 warnings in 27.80s
```
Все 406 тестов проекта (включая 9 новых тестов архивного конвейера и тест API) пройдены со 100% успехом.

### 2. Результаты линтеров и форматирования:
- `uv run ruff check`: `All checks passed!`
- `uv run ruff format --check`: `14 files already formatted`

### 3. Результаты проверки контракта валидатором:
```text
[*] Validating Archive Manifest Contract in l4desk-service/docs/prompts/contracts/archive-manifest-v1
  [+] JSON Schemas are valid Draft 2020-12
[*] Executing 13 acceptance vector cases...
  [PASS] iot-archive-verified (expected_valid=True, got=True)
  [PASS] media-archive-purged (expected_valid=True, got=True)
  [PASS] menubuilder-audit-prepared (expected_valid=True, got=True)
  [PASS] iot-archive-failed (expected_valid=True, got=True)
  [PASS] record-envelope-iot-event (expected_valid=True, got=True)
  [PASS] invalid-missing-file-sha256 (expected_valid=False, got=False)
  [PASS] invalid-verified-missing-verification (expected_valid=False, got=False)
  [PASS] invalid-purged-missing-purge (expected_valid=False, got=False)
  [PASS] invalid-owner-project (expected_valid=False, got=False)
  [PASS] invalid-retention-years-less-than-3 (expected_valid=False, got=False)
  [PASS] invalid-sha256-hex-pattern (expected_valid=False, got=False)
  [PASS] invalid-retention-window (expected_valid=False, got=False)
  [PASS] invalid-cursor-lag-purge (expected_valid=False, got=False)

[+] Acceptance Suite Summary: 13 passed, 0 failed
```

---

## 6. Выходной Handoff-блок Candidate

<!-- HANDOFF:H-L4D-15B-IOT-v1:BEGIN -->
```yaml
handoff_id: H-L4D-15B-IOT-v1
status: ACCEPTED
contract_kinds:
  - API
  - EVENT
  - DEPLOYMENT
producer_prompt_id: L4D-15B-IOT
producer_scope_project: iot-rpc-rest-app
producer_report_path: docs/l4desk/handoffs/L4D-15B-IOT-report.md
producer_branch: l4desk/l4d-15b-iot
producer_commit: af3b4f06456ddad2c8c44477dc52f25c49ee5722
accepted_at_utc: '2026-09-21T03:30:00Z'
contract_version: 1.0.0
schema_revision: '1.0.0'
artifact_version: 1.0.0
artifact_paths:
  - docs/l4desk/handoffs/L4D-15B-IOT-report.md
  - app-service/core/archive/pipeline.py
  - app-service/core/archive/canonical.py
  - app-service/core/archive/guards.py
  - app-service/core/models/archive.py
  - app-service/alembic/versions/2026_09_21_0007_add_fin_archive_batches.py
  - app-service/tests/core/test_l4d_15b_archive.py
compatibility:
  backward_compatible_with:
    - H-L4D-15A-DOCS-v1
    - H-L4D-02-IOT-v1
    - H-L4D-07-IOT-v1
  breaking_changes: false
  notes: "Full implementation of IoT/RPC monthly archive pipeline with deterministic JSONL.gz (mtime=0), SHA-256 manifest contract, staging-to-atomic promotion, consumer cursor guard, active records guard, and No-Financial-Purge bounded deletions."
deployment_status: DEPLOYED
deployed_environment: documentation
feature_flags:
  archive_worker_enabled: false
  archive_dry_run_default: false
contract_payload:
  manifest_version: "1.0.0"
  owner_project: "iot-rpc-rest-app"
  record_types:
    - "iot_session_events"
    - "rpc_transitions"
    - "presence_events"
  cursor_rules:
    through_cursor_source: "max(RemoteSessionEvent.cursor)"
    consumer_guard_condition: "consumers_passed_cursor >= through_cursor"
    on_lag_action: "abort_purge_mark_failed"
  purge_rules:
    financial_records_purged: false
    session_summaries_purged: false
    bounded_chunk_size: 1000
    pre_purge_verification_required: true
    recheck_active_records: true
  storage_rules:
    volume_root_configurable: true
    traversal_symlink_protected: true
    staging_prefix: ".tmp_"
    atomic_promotion: "os.replace"
    compression: "gzip (mtime=0.0)"
supersedes: []
known_risks: []
consumers:
  - L4D-15C-MEDIA
  - L4D-16-MB
next_prompt_id: L4D-15C-MEDIA
```
<!-- HANDOFF:H-L4D-15B-IOT-v1:END -->
