# Каскад промптов L4Desk

Каталог содержит исполняемые изолированные промпты реализации MVP из `..\l4desk-architecture.md`.

## Обязательный порядок запуска

1. Передать агенту содержимое ровно одного зарегистрированного файла промпта из таблиц ниже.
2. Обеспечить агенту read-only доступ к `PROMPT-STANDARD.md`, `contract-handoff.md`, разрешённым разделам архитектуры и конечному набору data-only входных артефактов по §10 стандарта.
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

## Зарегистрированные корректирующие шаги

| Заблокированный шаг | Corrective / файл | Scope | Регистрация в журнале | После выполнения |
|---|---|---|---|---|
| `L4D-06B-IOT` | `L4D-06B-IOT-FIX-01` / [etran_dev-l4d-06b-iot-fix-01.md](etran_dev-l4d-06b-iot-fix-01.md) | `iot-rpc-rest-app` | `R-L4D-06B-IOT-FIX-01-v3` (v1, v2 отозваны) | Повторная приёмка `L4D-06B-IOT`; не запуск `L4D-06C-MB` |
| `L4D-08B-MB` | `L4D-08B-MB-FIX-01` / [L4D-08B-MB-FIX-01.md](L4D-08B-MB-FIX-01.md) | `MenuBuilder` | `R-L4D-08B-MB-FIX-01-v1` | Повторная приёмка `L4D-08B-MB`; не запуск `L4D-09-MB` |
| `L4D-08B-MB` | `L4D-08B-FIX-01-MB` / [L4D-08B-FIX-01-MB.md](L4D-08B-FIX-01-MB.md) | `MenuBuilder` | `R-L4D-08B-FIX-01-MB-v1` | Замена media-flow `H-L4D-08B-MB-v1`; next `L4D-09-MB` |
| `L4D-13-MB` | `L4D-13-MB-FIX-01` / [L4D-13-MB-FIX-01.md](L4D-13-MB-FIX-01.md) | `MenuBuilder` | `R-L4D-13-MB-FIX-01-v1` | Замена UX-части `H-L4D-13-MB-v1`; next `L4D-14-MB` |

Регистрация и адресный допуск определяются §8 `PROMPT-STANDARD.md` и отдельной append-only записью `CORRECTIVE_REGISTRATION` в журнале. Прежние принятые записи не меняются. Предметный PIN-вход этого FIX заменён контроллером на `H-L4D-06A-PB-CONTRACT-01-v1` (самостоятельные документы, DOCS_PUBLISHED); `H-L4D-06A-PB-v1` остался только sequence gate без чтения исходников. Для `H-L4D-02-IOT-v1` оформлена точная привязка `B-L4D-02-IOT-GIT-v1` к опубликованным Git-байтам, отличающимся от исторических CRLF-копий. Для артефакта `docs/l4desk/contracts/schemas/remote_session.schema.json` контроллером нормативно установлено правило составного контейнера (§10.6 стандарта, раздел 10 журнала): схемы под `definitions` являются самостоятельными изолированными моделями, ссылка `#/$defs/RemoteSessionType` внутри `RemoteSessionCreate` валидно разрешается в её локальном `$defs`, валидация выполняется по моделям автономно. Для этого FIX согласован `DETACHED_V1`: окончательный candidate находится отдельно от отчёта и содержит SHA-256 зафиксированных байтов отчёта (§9 стандарта).

Документационный provider/corrective шаг `L4D-06A-PB-CONTRACT-01` выполнен контроллером по отдельному поручению пользователя; [отчёт](contracts/certificate-pin-v1/verification.md), [контракт](contracts/certificate-pin-v1/contract.md), [схемы](contracts/certificate-pin-v1/schemas.json), [примеры](contracts/certificate-pin-v1/examples.json) опубликованы в `1971e51f1e7764a31d586174e42513160f8598eb`. Runtime код/инфраструктура не изменялись; это не приёмка 06B.

Запись `AUTHORIZED` разрешает только указанный corrective scope и не является `ACCEPTED` runtime-handoff. Наличие записи в рабочем дереве не доказывает публикацию: перед запуском должны быть закоммичены и отправлены в remote промпт, регистрация и согласованные правила. Проверить опубликованный commit пакета. До принятия результата исходного `L4D-06B-IOT` основной каскад остаётся остановленным.

Для возобновления передать агенту точный файл FIX из **нового** commit D и сообщение контроллера с полным SHA D/подтверждением push в `origin/l4desk/l4d-06a-pb`. В сообщении указать: выполнить обновлённый FIX по стандарту 1.2.0 (§10.6), регистрации v3, четырём разрешённым PIN-документам, IOT byte binding и нормативному правилу разрешения схем RemoteSession; не читать семь .py старого 06A; вернуть отчёт и detached candidate для повторной приёмки. `b2664467...` не заменяет публикацию D. SHA D передаётся отдельно после commit, чтобы не создавать самоссылку в самом задании.

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

Сам факт ответа агента «готово» не является acceptance. Для запуска отдельного агента-контроллера фиксации handoff используется промпт `HANDOFF-CONTROLLER-PROMPT.md`.