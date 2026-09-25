# L4D-08B-FIX-03-MB — единая подтверждаемая остановка video remote session

## 1. Метаданные

- `prompt_id`: `L4D-08B-FIX-03-MB`
- `scope_project`: `MenuBuilder`
- `scope_root`: `D:\repo\platerra\Public\etranprocessing\MenuBuilder`
- `blocked_prompt_id`: `L4D-08B-FIX-01-MB`
- `sequence_gate_handoff_id`: `H-L4D-08B-FIX-01-MB-v1`
- `required_handoff_ids`:
  - `H-L4D-08B-FIX-01-MB-v1`
  - `H-L4D-07-IOT-STOP-v1`
- `output_handoff_id`: `H-L4D-08B-FIX-03-MB-v1`
- `next_prompt_id`: `L4D-13-MB-FIX-01`
- `report_path`: `MenuBuilder/docs/l4desk/handoffs/L4D-08B-FIX-03-MB-report.md`
- `candidate_path`: `MenuBuilder/docs/l4desk/handoffs/L4D-08B-FIX-03-MB-candidate.md`

## 2. Scope

Исполнитель изменяет только `MenuBuilder`. Изменять `iot-rpc-rest-app`, `l4media-ingress`, RabbitMQ, nginx или отключать защитный `409 session_busy` запрещено.

Задача: устранить известный residual risk принятого `H-L4D-08B-FIX-01-MB-v1` — параллельный stop-path в `video_control.py` вне `RemoteSessionUseCase`. Оба существующих HTTP-сценария остановки должны использовать одну идемпотентную backend-операцию для сохранённого `provider_session_id`.

## 3. Разрешённые внешние артефакты

Внешние файлы разрешено читать только как данные из commit `22a50a186da25dddb19612c475bf9bcbb4a7fab2`:

- `docs/l4desk/handoffs/remote-session-stop-contract-v1.1.md`
- `docs/l4desk/contracts/iot_event_feed_contract_v1.json`
- `docs/l4desk/contracts/schemas/iot_event_feed_openapi.json`
- `docs/l4desk/contracts/schemas/remote_session.schema.json`
- `docs/l4desk/fixtures/iot_event_feed_examples_v1.json`

Использовать код соседнего проекта как шаблон либо менять его запрещено.

## 4. Обязательное исследование до изменений

1. Найти фактические route handlers обоих stop-сценариев, текущий `RemoteSessionUseCase`, IoT adapter, media lifecycle client и место хранения `provider_session_id`.
2. Тестом воспроизвести дефект: первый route локально закрывает stream/media, второй больше не вызывает IoT stop, следующий start получает `409 session_busy`.
3. Подтвердить существующие транзакционные границы и восстановление после рестарта. Не переносить иллюстративные имена из этого промпта буквально, если код устроен иначе.
4. Если durable stop intent и `provider_session_id` нельзя сохранить существующей моделью, обосновать минимальную миграцию; не добавлять очередь, worker или Redis без доказанной необходимости.

## 5. Целевая операция stop

1. До сетевых вызовов сохранить stop intent, точный `provider_session_id`, `tenant_id`, `sn` и стабильный `operation_id`.
2. Оба HTTP-маршрута делегируют одной операции `RemoteSessionUseCase`; route-level IoT/media stop запрещён.
3. Операция координирует две существующие ответственности:
   - IoT provider подтверждает terminal state remote-session и отзывает принадлежащий ей input lease;
   - MenuBuilder через lifecycle API `l4media-ingress` останавливает media session.
4. Успех одной части не маскирует незавершённую другую. Локальная запись не получает `closed`, пока обязательные части не подтверждены.
5. Не держать транзакцию БД открытой во время сетевого ожидания. Повторный или параллельный stop присоединяется к той же операции.
6. Не искать «последнюю активную» IoT-сессию по SN и не закрывать новую сессию после запоздавшего ответа старой операции.

## 6. Семантика IoT-контракта v1.1

- `200`: тот же `session_id` находится в terminal state; можно продолжить/завершить локальную сходимость.
- timeout или потеря ответа: повторить stop с тем же ID/operation ID либо выполнить `GET` по тому же ID.
- `503 stop_teardown_failed`: оставить локальную операцию в `stopping`, выполнить bounded retry/backoff и durable reconciliation; не возвращать ложный success.
- `409 session_identity_mismatch`: terminal state не достигнут; зафиксировать контрактную ошибку и не подменять её `session_busy`.
- `404 not_found`: не выбирать другую сессию по SN; обработать как явное расхождение, требующее policy/reconciliation.
- create во время незавершённого stop не обходит `409 session_busy`; после подтверждённого stop новый start должен проходить без ожидания stale TTL.

## 7. Проверки

До исправления сохранить падающий regression test. После исправления проверить:

1. последовательность `stream/stop -> DELETE session -> start` без обновления страницы;
2. оба порядка двух stop-запросов, повтор и параллельный stop;
3. потерянный `200`, timeout, `404`, identity mismatch `409` и retryable `503`;
4. независимые сбои IoT stop и media stop без ложного `closed`;
5. restart процесса во время `stopping` и последующую сходимость;
6. late stop старого ID после создания новой сессии;
7. сохранение UI/API-совместимости и отсутствие direct ingress/Janus fallback;
8. все существующие тесты MenuBuilder, formatter/linter/type-checker проекта.

## 8. Наблюдаемость, rollout и rollback

- Добавить структурные логи с локальным session ID, provider session ID, operation ID и текущей фазой без секретов.
- Использовать метрики возраста `stopping`, числа retry/`503`, reconciliation mismatch и `409 session_busy` после подтверждённого stop.
- Provider `22a50a1` уже развёрнут первым; consumer переключать без изменения публичных HTTP-маршрутов.
- Rollback consumer не должен отключать `session_busy`, закрывать свежую `requested`-сессию или возвращать старый ложный success.

## 9. Выходной handoff

Отчёт и `DETACHED_V1` candidate должны содержать:

- схему состояний и фактический единый stop-path;
- список изменённых файлов и миграций;
- доказательство failing-before/passing-after и результаты полного релевантного suite;
- таблицу поведения `200/404/409/503/timeout/media failure/restart`;
- rollout/rollback и production smoke `stop -> immediate start`;
- `implementation_commit` и SHA-256 всех артефактов.

До публикации и принятия `H-L4D-08B-FIX-03-MB-v1` сквозная проблема считается только provider-ready, но не end-to-end resolved.