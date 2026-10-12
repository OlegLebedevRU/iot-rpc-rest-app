# Event75: внутренний регистр инвентаризации терминалов

Владельцы: терминал публикует наблюдение; IoT сохраняет событие и private outbox;
MenuBuilder сохраняет inbox и текущий snapshot. ProcessingBackend владеет миграцией
033 общей БД. Публичные API-вебхуки IoT сохраняют прежние настройки, формат,
заголовки, URL suffix, queue и статус доставки. Private delivery не использует
OrgWebhook и не расходует tenant webhook quota.

## Отбор и доставка

Allowlist внутреннего канала фиксирован в коде: **только 75**. Consumer также
принимает только 75; новые коды требуют изменения контракта и обеих сторон.
Событие и outbox записываются в одной транзакции IoT до EVA success. HTTP к MB
не вызывается из MQTT collector. Отдельный worker использует SKIP LOCKED, один
HTTP запрос с timeout 5 s, без вложенных повторов и redirects. Network/408/429/5xx
получают persisted exponential backoff до 1 h; 401/403/404 также повторяются,
поскольку receiver может ещё не быть выпущен или настроен. Другие 4xx изолируются
как quarantine через finished_at/last_error. Максимальный retry horizon — 30 дней.
Завершённые delivery хранятся 90 дней; cleanup ограничен 1000 строк в час.
Остановленный или медленный private worker не блокирует публичный webhook worker,
EVA или billing. Событие 75 не увеличивает IoT evt/activity billing counters.

При старте private worker один раз читает из **БД IoT**, пакетами по 500, последнее
событие 75 каждого устройства с прежним immutable owner, совпадающим с текущей
binding. Replay использует UUID из сохранённого correlationData; UUID не
восстанавливается из 101. Отсутствующий UUID/445 или несовпадающий SN пропускается
с диагностикой. Начальное заполнение ограничено 60 s и не блокирует app startup.
Последующие события доставляются через outbox, а не polling REST истории.

## Private HTTP v1

`POST /api/internal/v1/terminal-inventory/events`, скрыт из public OpenAPI.
Аутентификация — отдельный `X-Internal-Service-Key`, constant-time comparison.
Receiver использует `INVENTORY_DELIVERY_TOKEN`; producer —
`APP_CONFIG__INVENTORY_DELIVERY__TOKEN` и `APP_CONFIG__INVENTORY_DELIVERY__URL`.
Defaults пустые; credentials и URL задаются только runtime env. Общий auth токен
и credentials публичных вебхуков не подставляются автоматически.

Envelope: `v=1`, `tenant_id`, `device_id`, `sn`, `source_revision`, `event`.
Tenant/device/SN берутся из DB IoT, не из tenant payload. Перед каждой доставкой
worker повторно проверяет binding и SN; старую binding завершает без HTTP.
`source_revision` — положительный PK private outbox в постоянной БД IoT;
это server receipt order, **не 101**, UUID или MQTT packet ID. Replay/retry
сохраняет запись outbox. При восстановлении БД необходимо сохранить sequence;
сброс revision требует отдельного согласованного восстановления.

Raw event содержит `101` (positive31bit), `102` (aware UTC publication time),
`200=75`, ровно один объект `300`, `correlationData` (UUID).

| Тег | Обязательное значение |
| --- | --- |
| 324 | SN, совпадает с trusted envelope и записью MB |
| 440 | `l4con` |
| 441 | SHA1 thumbprint, 40 hex |
| 442 | Certificate serial, 1–40 hex |
| 443 | Aware certificate expiry |
| 444 | До 64 уникальных component names: name, nullable four-part file_version, x86/x64 arch |
| 445 | Непустая подтверждённая версия установленного комплекта, до 64 символов |

445 соответствует успешно завершённой установке всего комплекта; его нельзя
выводить из версии l4con, FILEVERSION другой EXE или доступного дистрибутива.
При частичном переключении 444 может содержать новые файлы при прежнем 445.
Отсутствующие EXE пропускаются; null FILEVERSION допустим; смесь x86/x64 допустима.
102 — время публикации, не установки. Raw контракт терминала предоставлен
пользователем в event-75.md; его пример не является наблюдением production 773.

## Приём и чтение

Receiver ограничивает envelope до 64 KiB и проверяет tenant/device/SN существующего
Terminal. Не создаёт терминалы, enrollment или certificate bindings. Берёт
identity lock терминала и UUID advisory lock; inbox и projection коммитятся вместе.
200 выдаётся после commit либо для уже подтверждённого duplicate. DB failure
не подтверждается. 403 — auth, 404 — отсутствующая identity, 409 — conflict,
413/422 — envelope/validation. Certificate observations сохраняются отдельно:
**Terminal.cert_serial не изменяется**.

UUID дедуплицируется по canonical payload hash с tenant/device/SN, без source_revision:
повтор replay с восстановленным outbox PK не превращает тот же факт в новый.
Изменённый payload того же UUID — conflict. Equal revision с другим UUID — conflict.
Lower revision или более ранний publication timestamp — durable outcome `older`,
без отката snapshot. Publication более чем на 5 min в будущем отклоняется.
Inbox хранится 120 дней, cleanup не более 1000 строк раз в 30 min на worker;
current snapshot сохраняет UUID/hash и не исчезает по давности.

`GET /settings/terminals?l4desk=true` читает PostgreSQL projection только для
страницы и возвращает `suite_version`, `inventory_published_at`, subscription,
user_disabled и batch presence. Фильтр состояния применяется до count/pagination.
Presence кешируется 30 s, tenant/ID scoped, с single-flight и concurrency 4;
один batch до 500 IDs, без обхода device API страниц. Missing/binding mismatch
не превращается в offline. Ошибка presence сохраняет доступность паспорта/версии.
UI показывает только версию; publication time и давность — в tooltip. Unknown
version не заменяется release version. Давность не доказывает изменения файлов:
агент публикует изменения, а не обязательный heartbeat каждые 60 s.

## Неагрессивное отключение

`PATCH /settings/terminals/{id}/activity` с `scope=l4desk` сохраняет
`L4DeskTerminal.user_disabled_at` и audit. Повтор задаёт то же состояние.
Административный is_active, enrollment, paid_until и free ordinal сохраняются.
MB admission запрещает новые использования и renew; cleanup остаётся доступным.
PB policy запрещает MQTT/RTP/FM после очередного чтения policy, не добавляя
stop_facts из-за одного пользовательского флага. Worker финансовых запретов не
останавливает сеансы только из-за этого флага. Финансовое истечение, удаление,
административный запрет и certificate expiry сохраняют свои отдельные правила.
RabbitMQ клиента не удаляет, соединения и usage не сканирует. Setup PIN для ручного
восстановления остаётся отдельной операцией и не включает отключённый терминал.

## Выпуск

Пуш в main/master; сборка и доставка только через builder и immutable digests.
Порядок: MB bridge 032/033 → PB migration033 → MB → frontend → IoT app1.
Private env provision выполняется проверенным `deploy/configure_inventory_delivery.py`:
сначала dry run, затем apply; значения не выводятся. Infrastructure containers
не пересоздаются. При откате expanded schema сохраняется. В handoff отдельно
фиксируются unit/browser checks, migration/health/revision/digest и фактическая
production доставка. Проверки очереди используют counts/outcomes без raw payload
или secret env.
