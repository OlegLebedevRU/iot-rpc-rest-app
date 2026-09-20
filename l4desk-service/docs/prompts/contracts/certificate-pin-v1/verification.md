# L4D-06A-PB-CONTRACT-01 — отчёт документационного provider-шага

Scope: `l4desk-service`; изменены только документы в `docs/prompts`.
Основание: явное поручение пользователя подготовить полный пакет для FIX и отдельное
подтверждение двухэтапного commit/push в `origin/l4desk/l4d-06a-pb`.
Результат локальной проверки: **VERIFIED**. Публикация и окончательное `ACCEPTED` фиксируются
контроллером в новом handoff только после push; отчёт не содержит собственного digest,
будущего commit или утверждения о ещё не выполненной публикации.

## Исходные версии и границы

- Baseline контроллера: `ddf39184d22e03ecf076569c982c06ab7ddfcd83`.
- Сверенная реализация PIN: `083138f223b723098e9a188803e3fc802e8a6011`.
- Второй вход: `H-L4D-02-IOT-v1`, commit `a5524d356dda343eca96010d16535d9f37ff4ece`.
- Ветка документационного пакета: `l4desk/l4d-06a-pb`, remote `https://github.com/OlegLebedevRU/etranprocessing.git`.
- Runtime, конфигурация, секреты, БД, MQTT и исходники соседнего репозитория не изменялись.
- Документальный export принятого API не является новым runtime-релизом. Backend pytest,
  ruff, pyright и сборка frontend не запускались согласно правилу docs-only.
- Проверка обработчиков, зависимостей и схем — статическая. Provider-модули не импортировались.
  Существующий тест row-locking не использован как доказательство конкурентной выдачи PIN.

## Реальные результаты

Рабочий каталог: `D:\repo\platerra\Public\etranprocessing`.
Python 3.14.0, PyYAML 6.0.3, jsonschema 4.26.0 с extra `format`.
Окончательный запуск: `2026-09-18T21:02:51Z`, exit code 0:

```powershell
uv run --no-project --with 'PyYAML==6.0.3' --with 'jsonschema[format]==4.26.0' python -u 'l4desk-service\docs\prompts\.verify-pin-package.py'
```

Временный проверочный скрипт не является контрактом и удаляется перед финальной публикацией.
Алгоритм: `git show <source_commit>:<path>` получал bytes, SHA-256 вычислялся до декодирования;
AST схемы сверял имена, обязательность, defaults, min/max с JSON Schema; `Draft202012Validator`
с `FormatChecker` проверял каждый fixture и дополнительные граничные значения.

| Проверка | Фактический итог |
|---|---|
| Семь исходных файлов PIN | HEAD идентичен исходному Git commit; классифицированы LF/CRLF digest |
| app/main.py (mounting, error envelope) | Без отличий от исходного commit |
| Пять JSON 02-IOT | Локальные CRLF-байты совпадают с журналом; Git LF-байты отдельно вычислены |
| JSON Schema Draft 2020-12 | Валидна |
| Синтетические fixtures | 20 положительных/отрицательных случаев: PASS |
| Дополнительные границы | 22 проверки: PASS (длины, TTL, null, PIN/status, даты) |
| Request против provider AST | Имена полей, defaults, required, границы: PASS |
| Прежний журнал | 72781 байт сохранён; SHA-256 `329844b0b829bf1f0a4d8dbe7f47fd8b5048852e435b33d0e8b376bf4c198802` |

Предварительные запуски: точная сверка исторического digest с Git выявила расхождение
переводов строк; оно не было объявлено совпадением. Затем один запуск прерван timeout.
Проверка невалидной даты выявила отсутствие optional format dependencies у jsonschema;
повтор с `jsonschema[format]` прошёл без изменения assertion. Это проверки документов,
не падение или успешный прогон тестов приложения.

## Точные Git-байты источника PIN

Пути ниже — provenance для контроллера, **не** дополнительный read grant смежному агенту.
Префикс первых пяти файлов: `ProcessingBackend/backend/app/`.

| Путь | SHA-256 Git blob в source commit |
|---|---|
| routers/certificates.py | `0a0e925b1dfad9c6b96f5063cc33b5bea822cd558062681d9b011f0fe02ed93a` |
| schemas/certificates.py | `72e44da075aa4286d78c52226522b2ebe5d931ba6dc1147cf235f2752563fa6e` |
| services/cert_billing.py | `32ecc1662d595433c5fee18e8503e4959d3efec25d83e788ab76393b8d4e7483` |
| dependencies.py | `dff777bcc6b875875e0812d39eb237ea7ce7a10ff990da6ae48b49e3cc2efa78` |
| config.py | `a3775f936e28b2b16c243e8391fd293788e4ff5b630592a31b7d9dfd1343639f` |
| ProcessingBackend/backend/app/models.py | `c75d5f9444b928b90a19a0d59836a818ecfb636730b1b7db3109de963f9b9cc7` |
| ProcessingBackend/backend/tests/test_certificate_pin_contract.py | `8f7ce51cef9a44efbcdfc265fc017f489ce3672682cfd64980e51184c3437068` |
| ProcessingBackend/backend/app/main.py | `b2d8591d26806064c2cf5253d01dd95da083f0883f8f979ca89fea10090303fe` |

Из семи artifact digest старого 06A только routers/certificates.py совпадает с Git blob.
Остальные шесть точно совпадают с теми же bytes после LF→CRLF. Контроллер установил
причину, но **не** переобъявляет старый полный artifact gate пройденным. Новый PIN handoff
ссылается только на этот самостоятельный опубликованный пакет с точными Git-byte digest.

## Переводы строк второго входа

Все пять исторических digest `H-L4D-02-IOT-v1` относятся к CRLF-копиям и совпадают с текущими
локальными файлами исполнителя. Соответствующие Git blobs содержат LF; bytes→CRLF даёт ровно
исторический digest, JSON-значения совпадают. Для переносимой проверки нового FIX контроллер
оформляет конечную append-only привязку digest Git-байтов. Она не меняет ID/semver/payload
02-IOT и не разрешает произвольную нормализацию при последующих проверках.

| Путь внутри iot-rpc-rest-app | SHA-256 Git blob в a5524d356dda343eca96010d16535d9f37ff4ece |
|---|---|
| docs/l4desk/contracts/iot_event_feed_contract_v1.json | `07be82d70e768ae0a44f24f6e5de6b948a039b746a798ce9c08179fbae810a77` |
| docs/l4desk/contracts/schemas/iot_event_feed_openapi.json | `8196befa2b3e103ec27cfbd39f65cbd230de55de037cadfbb890b06792d4d324` |
| docs/l4desk/contracts/schemas/remote_session_event.schema.json | `4d7393d0dcd1ae62f04e0ad488b6bab519d8d7e357f0cad569809743cb6270e9` |
| docs/l4desk/contracts/schemas/remote_session.schema.json | `c05027474d31f993954451d388667370caadcaeee044997a7a5a97e066cbb1ad` |
| docs/l4desk/fixtures/iot_event_feed_examples_v1.json | `41734c7b68850b083eefc07891183c91965c88d0a6589f15e265be0563006f61` |

## Изменённые файлы и публикация

Первый документационный commit содержит только четыре новых файла:

- `l4desk-service/docs/prompts/contracts/certificate-pin-v1/contract.md` — самостоятельная семантика API.
- `l4desk-service/docs/prompts/contracts/certificate-pin-v1/schemas.json` — wire schemas.
- `l4desk-service/docs/prompts/contracts/certificate-pin-v1/examples.json` — синтетические fixtures.
- `l4desk-service/docs/prompts/contracts/certificate-pin-v1/verification.md` — этот отчёт.

Во втором commit контроллер публикует append-only handoff, отзыв регистрации v1, регистрацию v2,
точную привязку IOT blobs, стандарт 1.2.0, инструкции и FIX. Их полные SHA и подтверждение push
передаются отдельно; самоссылок по commit/digest в этом отчёте нет.
Rollback: runtime не менялся; для отмены допуска нужна отдельная запись отзыва, не откат истории.
Переход к L4D-06C-MB закрыт до повторной приёмки L4D-06B-IOT.