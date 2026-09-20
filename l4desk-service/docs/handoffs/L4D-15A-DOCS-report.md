# L4D-15A-DOCS — Центральный отчёт о публикации Archive Manifest Contract v1

**Дата:** 2026-09-21  
**Промпт:** `L4D-15A-DOCS`  
**Пакет / Scope:** `l4desk-service` (`D:\repo\platerra\Public\etranprocessing\l4desk-service`)  
**Ветка:** `l4desk/l4d-15a-docs`  
**Статус:** `ACCEPTED`  
**Входной handoff (Sequence Gate):** `[H-L4D-14-MB-v1]`  
**Выходной handoff:** `H-L4D-15A-DOCS-v1`  
**Следующий промпт (consumer):** `L4D-15B-IOT` (дополнительные consumers: `L4D-15C-MEDIA`, `L4D-16-MB`)  
**Разделы архитектуры:** 3, 5, 6, 7, 10, 13, 14, 15, 16, 17, 18  

```yaml
prompt_id: L4D-15A-DOCS
scope_project: l4desk-service
scope_root: D:\repo\platerra\Public\etranprocessing\l4desk-service
prompt_type: contract-governance
required_handoff_ids: [H-L4D-14-MB-v1]
output_handoff_id: H-L4D-15A-DOCS-v1
next_prompt_id: L4D-15B-IOT
branch: l4desk/l4d-15a-docs
report_path: l4desk-service/docs/handoffs/L4D-15A-DOCS-report.md
architecture_sections: [3, 5, 6, 7, 10, 13, 14, 15, 16, 17, 18]
status: ACCEPTED
```

---

## 1. Резюме выполнения (Executive Summary)

В рамках задачи `L4D-15A-DOCS` в проекте документации и контрактного управления `l4desk-service` разработан и опубликован общий неизменяемый (immutable) нормативный контракт архивации — **Archive Manifest Contract v1**.

Контракт специфицирует правила и форматы для независимой реализации помесячной архивации в подсистемах IoT (`iot-rpc-rest-app`, шаг `L4D-15B-IOT`), Media (`l4media`, шаг `L4D-15C-MEDIA`) и интеграции в финансовый учет MenuBuilder (`L4D-16-MB`).

### Ключевые результаты шага:
1. **Sequence Gate & Входной контроль**:  
   - Успешно проверен входной handoff `H-L4D-14-MB-v1` (принят контроллером каскада со статусом `ACCEPTED`, потребителем указан `L4D-15A-DOCS`).
   - Использованы согласованные в Хабе и `shared/etranprocessing_db` идентификаторы (`archive_batch_id`, `owner_project`, `source_event_id`, `source_events_hash`, составной PK `(id, source_project)` в `fin_archive_batches`).
2. **Спецификация Archive Manifest Contract v1**:  
   - Определена структура канонического `manifest.json`: поля идентификации, временных диапазонов, ревизий схемы, типов и счетчиков записей, границ курсоров (`through_cursor`, `consumers_passed_cursor`), списка файлов с контрольными суммами SHA-256, жизненного цикла (`prepared`, `verified`, `purged`, `failed`), метаданных верификации, очистки и структурированных кодов ошибок.
3. **Архитектура размещения на смонтированном томе**:  
   - Стандартизирован layout: `<volume_root>/<year>/<month>/<project>/<archive_batch_id>/`.
   - Зафиксирован обязательный жизненный цикл временного каталога (`.tmp_<archive_batch_id>_<timestamp>`) внутри того же монтирования с принудительным `fsync` и атомарным переименованием (`rename(2)` / `os.replace`) только после успешного контрольного перечитывания.
4. **Формат MVP и детерминизм сериализации**:  
   - Утвержден формат сжатых данных: детерминированный UTF-8 `JSONL.gz` (без BOM, LF, ключи отсортированы, без лишних пробелов, временные метки ISO 8601 UTC с `Z`, целые копейки без `float`, `mtime=0` в заголовке gzip).
   - Стандартизирован сопутствующий файл контрольных сумм `checksum.sha256`.
5. **Барьеры безопасности очистки (Purge Safety Guards & Cursor Guard)**:  
   - Очистка оперативной БД разрешена исключительно после полного перечитывания архива, совпадения количества строк и контрольных сумм, успешного декодирования пробной выборки записей и подтверждения того, что курсоры всех обязательных потребителей прошли архивную границу (`consumers_passed_cursor >= through_cursor`).
   - Зафиксирован строгий инвариант `No-Financial-Purge`: финансовый сабледжер, платежи, тарифные версии, балансовые проекции, суточные агрегаты `FinUsageDaily` и итоговые строки сессий никогда не подлежат массовой очистке.
6. **Политика сроков хранения и резервного копирования**:  
   - Горячее окно хранения: строго 3 полных закрытых календарных месяца (относительно текущей даты).
   - Срок архивного хранения: не менее 3 лет (`retain_until >= created_at + 3 years`).
   - Смонтированный архивный том обязан входить в корпоративную схему резервного копирования.
7. **Инструментальная верификация схем и приёмочных векторов**:  
   - Разработаны канонические JSON-схемы (Draft 2020-12), golden fixtures и негативные acceptance vectors в `examples.json`.
   - Создан автономный тестовый раннер `validate_archive_manifest.py`.
   - Все 13 приёмочных тестов успешно пройдены (13 passed, 0 failed).
8. **Изоляция проекта (Scope Boundary)**:  
   - Runtime-репозитории не открывались и не модифицировались. Все артефакты созданы строго в каталоге `l4desk-service`.

---

## 2. Sequence Gate и верификация входного контракта

| Параметр | Значение | Статус Gate |
|---|---|:---:|
| Входной Handoff ID | `H-L4D-14-MB-v1` | **VALID** |
| Статус в журнале каскада | `ACCEPTED` (Раздел 24 `contract-handoff.md`) | **PASSED** |
| Продюсер | `MenuBuilder` (коммит `877dc00ac6e5131c65375c5494659d36ff31822e`) | **VERIFIED** |
| Целевой потребитель | `L4D-15A-DOCS` присутствует в `consumers` | **MATCH** |
| Согласованность схемы БД | Ревизия `027` Alembic (модели `fin_archive_batches`, `L4DeskSession`, `FinUsageDaily`) | **CONSISTENT** |

---

## 3. Сводная таблица артефактов контракта и контрольных сумм SHA-256

Все артефакты опубликованы в каталоге `l4desk-service/docs/prompts/contracts/archive-manifest-v1/`:

| № | Артефакт / Путь | Назначение | SHA-256 Digest |
|---|---|---|---|
| 1 | `l4desk-service/docs/prompts/contracts/archive-manifest-v1/archive-manifest.schema.json` | Каноническая JSON Schema Draft 2020-12 для `manifest.json` | `fc945431d6ceef34511fa40aea379588deb802a44a302061db102970c3d301fb` |
| 2 | `l4desk-service/docs/prompts/contracts/archive-manifest-v1/schemas.json` | Сводный пакет определений `$defs` (Manifest, FileEntry, RecordEnvelope, etc.) | `b769d3c45e4819e46d4d7455edd055e03fcf4388f6d2f23089d79c810961d55c` |
| 3 | `l4desk-service/docs/prompts/contracts/archive-manifest-v1/examples.json` | Канонические golden-фикстуры (IoT, Media, MenuBuilder) и негативные векторы | `a43a07a176dfa28b450dfa5fb456a0451028f95568f0852615168a863245cde2` |
| 4 | `l4desk-service/docs/prompts/contracts/archive-manifest-v1/contract.md` | Полная нормативная спецификация контракта | `71572b916c893c09cc0a11c662f826947f8470eed5b0743ffb86cfebecbc09f6` |
| 5 | `l4desk-service/docs/prompts/contracts/archive-manifest-v1/validate_archive_manifest.py` | Автономный исполняемый тестовый раннер валидации | `d9953d93a3fe1f3d635825802c6054cfbca51e2f1b12b0059b2929cc25a77b6b` |
| 6 | `l4desk-service/docs/prompts/contracts/archive-manifest-v1/verification.md` | Отчёт о доказательной верификации пакета | `e27d848f8226415f216a3627a6b63636f5bd92729eddd471a54b2fd92fafa905` |

---

## 4. Результаты валидации приёмочных векторов (Acceptance Vectors)

Запуск тестового раннера:
```powershell
uv run --no-project --with "jsonschema[format]==4.26.0" python l4desk-service\docs\prompts\contracts\archive-manifest-v1\validate_archive_manifest.py
```

### Протокол исполнения:
1. `[+] JSON Schemas are valid Draft 2020-12` — **PASSED**
2. `[PASS] iot-archive-verified` (expected_valid=True, got=True) — **PASSED**
3. `[PASS] media-archive-purged` (expected_valid=True, got=True) — **PASSED**
4. `[PASS] menubuilder-audit-prepared` (expected_valid=True, got=True) — **PASSED**
5. `[PASS] iot-archive-failed` (expected_valid=True, got=True) — **PASSED**
6. `[PASS] record-envelope-iot-event` (expected_valid=True, got=True) — **PASSED**
7. `[PASS] invalid-missing-file-sha256` (expected_valid=False, got=False) — **PASSED**
8. `[PASS] invalid-verified-missing-verification` (expected_valid=False, got=False) — **PASSED**
9. `[PASS] invalid-purged-missing-purge` (expected_valid=False, got=False) — **PASSED**
10. `[PASS] invalid-owner-project` (expected_valid=False, got=False) — **PASSED**
11. `[PASS] invalid-retention-years-less-than-3` (expected_valid=False, got=False) — **PASSED**
12. `[PASS] invalid-sha256-hex-pattern` (expected_valid=False, got=False) — **PASSED**
13. `[PASS] invalid-retention-window` (expected_valid=False, got=False) — **PASSED**
14. `[PASS] invalid-cursor-lag-purge` (expected_valid=False, got=False) — **PASSED**

Итоговый результат: **13 passed, 0 failed**.

---

## 5. Инструкции и обязательные инварианты для последующих шагов

### 5.1. Для шага `L4D-15B-IOT` (`iot-rpc-rest-app`):
- Использовать `archive_batch_id` в формате `arch-iot-<YYYY-MM>-<suffix>`.
- Архивировать только owned high-volume IoT details (`iot_session_events`, RPC transitions, presence history).
- Проверять продвижение курсора суточного использования `consumers_passed_cursor >= through_cursor` перед началом очистки БД.
- Использовать детерминированный gzip (`mtime=0`) и канонический JSONL.
- Производить порционную очистку (чанками по 500–1000 строк) без блокировки оперативной обработки сессий.

### 5.2. Для шага `L4D-15C-MEDIA` (`l4media`):
- Использовать `archive_batch_id` в формате `arch-media-<YYYY-MM>-<suffix>`.
- Архивировать технические медиа-семплы, метрики качества WebRTC/RTP и ingress logs старше 3 полных месяцев.
- Не затрагивать данные активных стримов и общие сессионные сводки.
- Обеспечивать идентичный жизненный цикл: temp directory → `fsync` → SHA-256 → reread → atomic rename → verified → purge.

### 5.3. Для шага `L4D-16-MB` (`MenuBuilder`):
- Импортировать опубликованные манифесты в таблицу `fin_archive_batches` по составному ключу `(id, source_project)`.
- Валидировать схему и контрольные суммы манифестов перед регистрацией.
- Отображать состояние архивных пакетов в superuser Хабе без раскрытия физических путей тома обычным пользователям.
- Никогда не удалять финансовые проводки, суточные начисления `FinUsageDaily` и балансы.

---

## 6. Заключение

Контракт `H-L4D-15A-DOCS-v1` полностью сформирован, верифицирован и готов к регистрации в журнале каскада `contract-handoff.md`. Каскад готов к началу реализации архивации IoT-подробностей на шаге `L4D-15B-IOT`.
