# Archive Manifest Contract v1 — Отчёт о верификации пакета

Scope: `l4desk-service`; изменения строго ограничены проектом документации и контрактного управления `l4desk-service`.  
Основание: выполнение промпта `L4D-15A-DOCS`, принятый входной handoff `H-L4D-14-MB-v1`.  
Результат проверки: **VERIFIED**.

---

## 1. Назначение и границы проверки

В рамках задачи `L4D-15A-DOCS` опубликован общий нормативный контракт Archive Manifest Contract v1 для независимой реализации помесячной архивации в подсистемах IoT (`L4D-15B-IOT`), Media (`L4D-15C-MEDIA`) и MenuBuilder (`L4D-16-MB`).

В соответствии с правилами изоляции:
1. Runtime-репозитории не открывались и не модифицировались.
2. Проверка схем и фикстур выполнена изолированным валидатором на базе JSON Schema Draft 2020-12 с FormatChecker.
3. Доказаны все инварианты жизненного цикла пакета, правила детерминизма, барьеры безопасности очистки (Purge Guards), границы курсоров и сроки хранения (3 месяца hot / 3 года архив).

---

## 2. Результаты исполнения приёмочного набора (Acceptance Suite)

Исполняемый раннер: `validate_archive_manifest.py`  
Среда: Python 3.14.0, jsonschema 4.26.0 (с экстра-модулем `format`).  
Команда запуска:
```powershell
uv run --no-project --with "jsonschema[format]==4.26.0" python l4desk-service\docs\prompts\contracts\archive-manifest-v1\validate_archive_manifest.py
```

### Результаты тестирования:

| № | Идентификатор кейса | Схема / Тип | Ожидание | Факт | Описание проверки |
|---|---|---|:---:|:---:|---|
| 1 | `iot-archive-verified` | `ArchiveManifest` | VALID | **PASS** | Валидный проверенный архив IoT-событий (2026-05) со всеми метаданными и курсорами |
| 2 | `media-archive-purged` | `ArchiveManifest` | VALID | **PASS** | Полностью очищенный архив медиа-телеметрии (2026-04) |
| 3 | `menubuilder-audit-prepared` | `ArchiveManifest` | VALID | **PASS** | Подготовленный staging-пакет аудита MenuBuilder (2026-05) в состоянии `prepared` |
| 4 | `iot-archive-failed` | `ArchiveManifest` | VALID | **PASS** | Корректно зафиксированный аварийный пакет со статусом `failed` и ошибкой `CHECKSUM_MISMATCH` |
| 5 | `record-envelope-iot-event` | `RecordEnvelope` | VALID | **PASS** | Канонический конверт записи JSONL для IoT-события сессии |
| 6 | `invalid-missing-file-sha256` | `ArchiveManifest` | INVALID | **PASS** | Отклонение файла без обязательной контрольной суммы SHA-256 |
| 7 | `invalid-verified-missing-verification` | `ArchiveManifest` | INVALID | **PASS** | Отклонение статуса `verified` при отсутствии объекта верификации |
| 8 | `invalid-purged-missing-purge` | `ArchiveManifest` | INVALID | **PASS** | Отклонение статуса `purged` при отсутствии метаданных очистки |
| 9 | `invalid-owner-project` | `ArchiveManifest` | INVALID | **PASS** | Отклонение неизвестного владельца проекта вне допустимого перечня `enum` |
| 10 | `invalid-retention-years-less-than-3` | `ArchiveManifest` | INVALID | **PASS** | Отклонение срока хранения менее 3 лет |
| 11 | `invalid-sha256-hex-pattern` | `ArchiveManifest` | INVALID | **PASS** | Отклонение нешестнадцатеричного или некорректного по длине хеша SHA-256 |
| 12 | `invalid-retention-window` | `ArchiveManifest` | INVALID | **PASS** | Защита горячего окна: отклонение попытки архивировать данные за 2026-08 (моложе 3 полных месяцев) |
| 13 | `invalid-cursor-lag-purge` | `ArchiveManifest` | INVALID | **PASS** | Consumer Cursor Guard: отклонение `purged` при отставании курсора потребителя (19500 < 20000) |

Итог: **13 passed, 0 failed**.

---

## 3. Побайтовые контрольные суммы артефактов (Artifact SHA-256 Digests)

| Файл | Описание назначения | SHA-256 Digest |
|---|---|---|
| `archive-manifest.schema.json` | Каноническая JSON-схема манифеста (Draft 2020-12) | `fc945431d6ceef34511fa40aea379588deb802a44a302061db102970c3d301fb` |
| `schemas.json` | Сводный бандл схем (Manifest, FileEntry, RecordEnvelope, etc.) | `b769d3c45e4819e46d4d7455edd055e03fcf4388f6d2f23089d79c810961d55c` |
| `examples.json` | Канонические golden-фикстуры и 13 приёмочных тестовых векторов | `a43a07a176dfa28b450dfa5fb456a0451028f95568f0852615168a863245cde2` |
| `contract.md` | Полная нормативная спецификация контракта | `71572b916c893c09cc0a11c662f826947f8470eed5b0743ffb86cfebecbc09f6` |
| `validate_archive_manifest.py` | Автономный тестовый раннер валидации | `d9953d93a3fe1f3d635825802c6054cfbca51e2f1b12b0059b2929cc25a77b6b` |

---

## 4. Архитектурные инварианты контракта

1. **Идемпотентность и атомарность (Staging & Atomic Rename)**:  
   Создание батча происходит во временном каталоге `.tmp_<archive_batch_id>_<timestamp>` на том же томе. Каталог перемещается в целевой `<archive_batch_id>` только после успешного прохождения верификации.
2. **Гарантия целостности (Full Reread & Checksum)**:  
   Перед подтверждением статуса `verified` воркер архивации обязан полностью перечитать сжатый файл данных `data.jsonl.gz`, сверить количество строк и побайтовый хеш SHA-256.
3. **Consumer Cursor Guard**:  
   Очистка (purge) записей из оперативной базы данных категорически запрещена, если курсор обязательного внешнего потребителя (`consumers_passed_cursor`) не достиг или отстаёт от верхней границы батча (`through_cursor`).
4. **No-Financial-Purge Invariant**:  
   Финансовый сабледжер (`fin_*`), платежи, тарифы, начисления, суточные агрегаты `FinUsageDaily` и итоговые строки сессий никогда не подлежат удалению при очистке технического архива.
5. **Горячий и архивный сроки хранения (Retention Policy)**:  
   В горячей БД сохраняются данные за текущий и 3 полных закрытых календарных месяца. Архивные файлы на смонтированном томе хранятся не менее 3 лет и обязательно включаются в корпоративное резервное копирование.
