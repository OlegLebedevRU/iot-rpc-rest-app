# Каскад промптов L4Desk

Каталог содержит исполняемые изолированные промпты реализации MVP из `..\l4desk-architecture.md`.

## Обязательный порядок запуска

1. Передать агенту содержимое ровно одного файла `L4D-*.md`.
2. Обеспечить агенту read-only доступ к `PROMPT-STANDARD.md`, `contract-handoff.md` и разрешённым разделам архитектуры.
3. Не запускать промпты параллельно и не пропускать строки списка ниже.
4. После выполнения runtime-промпта проверить локальный отчёт и candidate handoff.
5. Контроллер дословно добавляет проверенный candidate в `contract-handoff.md` только при полном `ACCEPTED`.
6. Лишь после commit/push общего журнала запускается следующий файл.
7. При любом blocker создаётся corrective prompt по `CORRECTIVE-PROMPT-TEMPLATE.md`; основной каскад приостановлен до нового принятого handoff.

Агент никогда не восстанавливает отсутствующий контракт по коду соседнего проекта. Единственный контрактный input — точный `ACCEPTED`-блок из `contract-handoff.md` и перечисленные в нём immutable artifacts с digest.

## Последовательность

| № | Файл | Единственный scope |
|---:|---|---|
| 1 | `L4D-00A-TOOLS.md` | `tools` |
| 2 | `L4D-00B-IOT.md` | `iot-rpc-rest-app` |
| 3 | `L4D-00C-PB.md` | `ProcessingBackend` |
| 4 | `L4D-00D-MEDIA.md` | `l4media` |
| 5 | `L4D-00E-MB.md` | `MenuBuilder` |
| 6 | `L4D-00F-SHARED.md` | `shared/etranprocessing_db` |
| 7 | `L4D-00G-DOCS.md` | `l4desk-service` |
| 8 | `L4D-01A-TOOLS.md` | `tools` |
| 9 | `L4D-01B-IOT.md` | `iot-rpc-rest-app` |
| 10 | `L4D-01C-DOCS.md` | `l4desk-service` |
| 11 | `L4D-02-IOT.md` | `iot-rpc-rest-app` |
| 12 | `L4D-03-MB.md` | `MenuBuilder` |
| 13 | `L4D-04A-SHARED.md` | `shared/etranprocessing_db` |
| 14 | `L4D-04B-PB.md` | `ProcessingBackend` |
| 15 | `L4D-04C-MB.md` | `MenuBuilder` |
| 16 | `L4D-05-MB.md` | `MenuBuilder` |
| 17 | `L4D-06A-PB.md` | `ProcessingBackend` |
| 18 | `L4D-06B-IOT.md` | `iot-rpc-rest-app` |
| 19 | `L4D-06C-MB.md` | `MenuBuilder` |
| 20 | `L4D-07-IOT.md` | `iot-rpc-rest-app` |
| 21 | `L4D-08A-MEDIA.md` | `l4media` |
| 22 | `L4D-08B-MB.md` | `MenuBuilder` |
| 23 | `L4D-09-MB.md` | `MenuBuilder` |
| 24 | `L4D-10-MB.md` | `MenuBuilder` |
| 25 | `L4D-11-MB.md` | `MenuBuilder` |
| 26 | `L4D-12-MB.md` | `MenuBuilder` |
| 27 | `L4D-13-MB.md` | `MenuBuilder` |
| 28 | `L4D-14-MB.md` | `MenuBuilder` |
| 29 | `L4D-15A-DOCS.md` | `l4desk-service` |
| 30 | `L4D-15B-IOT.md` | `iot-rpc-rest-app` |
| 31 | `L4D-15C-MEDIA.md` | `l4media` |
| 32 | `L4D-16-MB.md` | `MenuBuilder` |
| 33 | `L4D-17A-TOOLS.md` | `tools` |
| 34 | `L4D-17B-PB.md` | `ProcessingBackend` |
| 35 | `L4D-17C-IOT.md` | `iot-rpc-rest-app` |
| 36 | `L4D-17D-MEDIA.md` | `l4media` |
| 37 | `L4D-17E-MB.md` | `MenuBuilder` |
| 38 | `L4D-17F-DOCS.md` | `l4desk-service` |
| 39 | `L4D-18A-SHARED.md` | `shared/etranprocessing_db` |
| 40 | `L4D-18B-PB.md` | `ProcessingBackend` |
| 41 | `L4D-18C-IOT.md` | `iot-rpc-rest-app` |
| 42 | `L4D-18D-MEDIA.md` | `l4media` |
| 43 | `L4D-18E-MB.md` | `MenuBuilder` |
| 44 | `L4D-18F-DOCS.md` | `l4desk-service` |

## Acceptance контроллера

Перед добавлением handoff контроллер проверяет:

- scope не вышел за один проект;
- отсутствуют незаявленные изменения;
- обязательные тесты зелёные;
- commit существует в указанной remote-ветке;
- deploy/publish и smoke подтверждены;
- artifact paths доступны и их SHA-256 совпадает;
- contract payload полон и не содержит предположений;
- `consumers` и `next_prompt_id` совпадают с последовательностью;
- в журнале нет конфликтующего handoff.

Сам факт ответа агента «готово» не является acceptance.