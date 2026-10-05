# L4FM v2: итоговый контракт IoT/app1

Актуально 2026-10-05. Реализация app1 выпущена из master
`6209faf870d9d05028255c9e92f30017a33be781`. Серверная документация не означает
новый deploy: обновление master само по себе не заменяет работающий образ.
Смежный etranprocessing: PB/MB b8c609e, frontend 09b22e8, suite 1.13.1 / L4Con 1.12.1.

Полная архитектура, UI/Windows/S3 и roadmap находятся у владельца продукта:
[etranprocessing: L4FM](https://github.com/OlegLebedevRU/etranprocessing/blob/main/docs/etran_arch-file-manager-remote-windows.md).
Здесь фиксируется контракт app1, чтобы новые изменения не вернули v1 или
параллельную lease. Байты файлов — только browser↔S3↔agent; app1/PB/MB не relay.
Все agent HTTP проходят через Leo4Proxy; agent metadata идёт в PB, не app1.

## Владельцы и общий сеанс

IoT — единственный владелец shared lease для files/console/stream/input/view.
FM не исключает конфликт для того же пользователя или browser view. Acquire
не является renew. Redis WATCH защищает active key и lease hash, revoke нельзя
обойти повторным acquire. MB передаёт проверенный actor context и browser-view
owner; internal FM API требует service authorization. PB хранит operation state,
выдаёт tickets/grants и проверяет checksum/VersionId/commit, не создаёт вторую lease.

Start: reserve → PB metadata → RPC7023/start → PB ticket/agent ACK → UI active.
Renew: IoT touch → RPC7023/renew → применение нового grant/deadline агентом → PB ACK.
Одна публикация MQTT/RES не доказывает применения lease или целостности файла.
Close/cancel: revoke first, отдельный fmc stop, worker-exit ACK, затем
confirm_files_stopped. Без подтверждения остаётся guard deadline +5 с.
Нельзя заменить эту последовательность unconfirmed close или вызовом старого RPC.

## Каналы и конфигурация

| Flow | Producer → consumer | Payload / результат |
|---|---|---|
| Start/renew | app1 → l4con, существующий RPC7023 | session_id/action/expires_at/ttl_sec; без operation_id |
| Transfer | app1 → l4con, RPC7021 | session_id/action=transfer/operation_id/expires_at/ttl_sec |
| Navigation | app1 → `srv/{SN}/fmc` | v=2, command_id, lease_id, action=list, path, offset, expires_at |
| Stop | app1 → `srv/{SN}/fmc` | тот же v2 envelope, action=stop, без path/offset |
| Result | l4con → `dev/{SN}/fmr` | v=2, command_id, lease_id, completed/failed, entries, has_more, error_code |

7020/7022 и 7023 action=stop отклоняются. FM protocol 1 не поддерживается.
HTTP prefix /v1 сохранён как namespace, а не compatibility promise.
`dev/{SN}/svc` остаётся retained presence extra_service; fmc/fmr — без retain.
Console out не переиспользуется: отдельный канал изолирует schema/TTL/error handling.

- `core/config.py`: suffix_fm_command=fmc, suffix_fm_result=fmr,
  fm_queue_name=fm_result_v1. Последнее — имя очереди, wire принимает только v2.
- `core/topologys/declare.py`: amq.topic publish `srv.<SN>.fmc`, binding
  `dev.*.fmr` → fm_result_v1. Subscriber извлекает SN из routing key и вызывает
  bounded validator. MQTT bridge/agent QoS1; ACK не является exactly-once execution.
- На терминале l4setup/l4superv создают Mosquitto contract 3: dev outbound
  app/svc/evt/req/res/out/ctl/fmr; srv inbound tsk/rsp/eva/cmt/ctl/fmc, все QoS 1.
  Wildcard и дублирование запрещены. Старый own-SN wildcard — только вход
  миграции; чужие/неизвестные routes не расширяют allowlist.
- Native l4con подписывается на fmc и публикует fmr с correlationData=command_id.
  Изменение suffix в app1 требует согласованного изменения всех участников;
  наличие server config поля не делает произвольный суффикс совместимым.

## Bounded request/reply

`core/file_manager_navigation.py`: до publish создаются Redis pending SN+lease и
per-action guard. У list и stop разные guards: зависший list не блокирует stop.
TTL pending/guard/result — 10 с; broker expiry и ожидание — 7 с; Redis poll — 100 мс.
Command expiry list дополнительно ограничен lease; stop имеет собственное короткое
окно доставки, чтобы закрыть уже revoked lease. Guard удаляется compare-delete.

Ожидание находится в текущем HTTP request BFF→app1. Это не WebSocket, outbox или
автоповтор. Timeout/ошибка revokes lease. При чтении reply снова проверяется lease.
SN, UUID canonical form, lease_id, version, schema и размер проверяются перед
записью результата; первый валидный ответ побеждает через SET NX. Поздние/чужие
ответы и дубликаты не продлевают lease и не становятся результатом нового запроса.

Полная страница: не более 64 entries и 24 КиБ JSON. Частичный response не отдаётся.
Path — metadata (не file bytes); URL S3 и содержимого файла в fmc/fmr нет.
Сортирует l4con до pagination: directories→files/natural name, до 65 536 видимых
entries; offset не даёт snapshot при изменении каталога между запросами.

## Проверки и оставшиеся риски

- Local Windows suite при реализации: 545 passed / 7 skipped; builder gate passed.
- При production выпуске: fmr binding, два consumer и нулевой backlog проверены.
- Live 1000007 / suite 1.13.0: start, drives/list/parent, upload+autorefresh,
  download SHA256, home/close/reopen и console admission после закрытия FM.
- Suite1.13.1 установлена через l4mcp, службы/версии/подписи и PB registration
  проверены; desktop locked, live interactive sorting/Save As не повторены.
- Эти наблюдения не закрывают полную fault matrix: Redis/broker reconnect,
  lost/late/duplicate ACK, concurrent workers/leases, policy deny, native crash,
  user token boundaries и длительную нагрузку suite.

Ближайший план app1: P0 — fault/soak и измерение safe-drain; P1 — metrics
latency/timeout/invalid replies без secret payloads, оценка стоимости Redis polling.
Push/WS или outbox обсуждать после измерений, сохраняя TTL, ownership и stop ACK;
не возвращать v1 fallback, same-owner bypass или server relay.

## Исходники

- [FM router](../app-service/api/internal_v1/file_manager.py).
- [Navigation/correlation](../app-service/core/file_manager_navigation.py).
- [Lease registry](../app-service/core/remote_input/leases.py).
- [Topology](../app-service/core/topologys/declare.py), [configuration](../app-service/core/config.py).
- [Topic rules](mqtt_topic_rules.md), [method registry](method-codes-reference.md).

Финализация документации не запускала новые broker/terminal/server probes или deploy.
