# IoT Remote Session Stop Contract v1.1

Дата: `2026-09-25`

Scope: только `iot-rpc-rest-app/app-service`. MenuBuilder и frontend не изменялись.

## Назначение

Контракт устраняет неоднозначность между «операция остановки принята» и «IoT-сессия подтверждённо закрыта». Он не ослабляет взаимное исключение и не закрывает свежую `requested`-сессию по состоянию медиапотока.

Канонический machine-readable контракт: `docs/l4desk/contracts/iot_event_feed_contract_v1.json`, версия `1.1.0`, schema revision `2026-09-25-v2`.

## Endpoint и авторизация

- Stop: `POST /api/internal/v1/remote-sessions/{session_id}/stop`.
- Reconcile: `GET /api/internal/v1/remote-sessions/{session_id}`.
- Create: `POST /api/internal/v1/remote-sessions`.
- Авторизация: `X-Internal-Service-Key` либо `Authorization: Bearer <key>` через существующий `Internal_Auth_dep`; неверный ключ возвращает `403`.
- Stop всегда адресует конкретный неизменяемый `session_id`. Поиск «последней активной» сессии по SN не выполняется.

Пример stop-запроса:

```json
{
  "operation_id": "stop-7e9c8b4a",
  "tenant_id": 42,
  "sn": "a4b0000070c66671d210826",
  "reason": "user_requested",
  "correlation_id": "menu-stop-c90f",
  "timeout_sec": 5.0
}
```

`tenant_id` и `sn` аддитивны и необязательны для обратной совместимости. Новому потребителю рекомендуется всегда передавать оба поля как защиту от устаревшего запроса.

## Семантика ответов

| HTTP | Код | Значение |
|---|---|---|
| `200` | — | Возвращена зафиксированная терминальная запись. Для обычного stop это означает `status=closed`, завершённый resource teardown и durable `remote_session_closed`. Повтор после потерянного ответа возвращает ту же запись без повторного teardown. |
| `403` | — | Не пройдена внутренняя сервисная авторизация. |
| `404` | `not_found` | Точный `session_id` неизвестен. Другая сессия не выбирается и не останавливается. |
| `409` | `session_identity_mismatch` | Переданный `tenant_id` или `sn` не совпал с записью. Состояние и ресурсы не изменяются. |
| `503` | `stop_teardown_failed` | Освобождение ресурсов не завершилось. Сессия зафиксирована как `stopping`, `retryable=true`; это не успешное закрытие. |
| `422` | — | Тело запроса не прошло schema validation. |

Пример retryable-ошибки:

```json
{
  "detail": {
    "code": "stop_teardown_failed",
    "message": "Resource teardown failed for remote session 'sess-video-123'",
    "session_id": "sess-video-123",
    "status": "stopping",
    "retryable": true
  }
}
```

## Переходы и конкуренция

```text
requested | starting | active
            |
            | stop(session_id, tenant_id?, sn?)
            v
         stopping -- teardown success --> closed
            |
            +-- teardown failure --> stopping + HTTP 503
                                      |
                                      +-- safe retry/reconcile
```

- `requested`, `starting`, `active` и `stopping` остаются блокирующими для create на том же SN. Настоящий конфликт продолжает возвращать `409 session_busy`.
- Stop одной сессии сериализуется row lock базы данных, поэтому гарантия действует между worker/process, а не только внутри одного event loop.
- Параллельный или повторный stop присоединяется к состоянию той же записи; создаётся не более одной пары событий `remote_session_stop_requested` / `remote_session_closed` и выполняется не более одного успешного teardown.
- После ошибки teardown durable `stopping` переживает перезапуск worker. Повтор по тому же `session_id` продолжает остановку.
- Поздний stop старого terminal session ID возвращает его terminal state и не трогает новую сессию.
- Lease отзывается только если он не имеет owner либо `owner_session_id` совпадает с останавливаемой сессией. Lease новой/чужой сессии не отзывается.
- Stale eviction через 60 секунд сохранён только как fallback восстановления; он не является штатным подтверждением stop.

## Правило потребителя

1. Сохранить provider `session_id` и stop intent до сетевого вызова.
2. Вызвать stop с тем же `session_id`, `tenant_id`, `sn` и стабильным `operation_id`.
3. Считать остановку подтверждённой только после `200` с terminal state либо после `GET` того же `session_id`, вернувшего terminal state.
4. При timeout/потере ответа повторить stop или выполнить GET по тому же ID; не выбирать сессию по SN.
5. При `503` оставить локальную операцию в `stopping`, применить bounded retry/backoff и reconciliation.
6. Не запускать конкурирующую сессию, пока stop не подтверждён. `409 session_busy` в этот период является защитным поведением.

## Наблюдаемость

Минимальные метрики/алерты provider и consumer:

- возраст сессий в `stopping` (`now - updated_at`), alert при превышении согласованного retry window;
- количество `stop_teardown_failed` и повторов stop по `session_id`;
- количество `session_identity_mismatch`;
- `409 session_busy` после подтверждённого consumer-side stop;
- расхождение consumer state и `GET /remote-sessions/{session_id}`;
- отсутствие пары `remote_session_closed` после `remote_session_stop_requested` в пределах SLA.

Логи teardown содержат `session_id`; попытка отозвать lease другого owner фиксируется warning без мутации ресурса.

## Rollout и rollback

Rollout:

1. Развернуть IoT provider версии контракта `1.1.0` до изменения MenuBuilder.
2. Проверить OpenAPI, internal auth, `200/404/409/503` и event feed на staging.
3. Включить consumer-передачу `tenant_id`/`sn`, retry/reconcile и трактовку `503` как незавершённого stop.
4. Переключить оба consumer stop-маршрута на одну операцию по сохранённому provider `session_id`.
5. Наблюдать метрики `stopping`, teardown failures и `409` после stop.

Rollback:

- Consumer может откатиться первым: новые поля необязательны, старые тела stop остаются валидными.
- Provider можно откатить после consumer; consumer обязан временно не полагаться на новые `409/503` details.
- Миграция БД не требуется и rollback схемы отсутствует.
- Нельзя откатывать исправление путём автоматического закрытия свежей `requested`-сессии или отключения `session_busy`.

## Изменённые артефакты и тестовые доказательства

- `app-service/core/schemas/remote_sessions.py`: аддитивные `tenant_id`/`sn` guards.
- `app-service/core/services/remote_session_event_service.py`: row lock, identity validation, retryable durable stopping, строгий lease ownership.
- `app-service/api/internal_v1/remote_sessions.py`: явные `409` и `503`, `200` только после commit terminal state.
- `app-service/tests/core/test_l4d_07_session_lock_and_graceful_stop.py`: потерянный ответ, row lock, tenant/SN mismatch, teardown failure + restart retry, late old stop.
- `app-service/tests/core/test_l4d_02_event_feed_full.py`: генерация контрактных артефактов `1.1.0`.
- `docs/l4desk/contracts/iot_event_feed_contract_v1.json`: канонический контракт.
- `docs/l4desk/contracts/schemas/iot_event_feed_openapi.json` и `remote_session.schema.json`: сгенерированные схемы.
- `docs/l4desk/fixtures/iot_event_feed_examples_v1.json`: golden examples с новой revision.

Миграций нет: реализация использует существующие таблицы, durable events и индекс `uq_active_remote_session_per_sn`.