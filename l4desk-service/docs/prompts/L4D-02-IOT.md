# L4D-02-IOT — Реализовать durable session facts и event feed

```yaml
prompt_id: L4D-02-IOT
scope_project: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
prompt_type: implementation-provider
required_handoff_ids: [H-L4D-01C-DOCS-v1]
output_handoff_id: H-L4D-02-IOT-v1
next_prompt_id: L4D-03-MB
branch: l4desk/l4d-02-iot
report_path: docs/l4desk/handoffs/L4D-02-IOT-report.md
architecture_sections: [3, 4, 5, 6, 8, 11, 12, 15, 16, 17]
```

## Цель

Только в `iot-rpc-rest-app` создай надёжные device/session facts и versioned cursor event feed для внешнего consumer. Не проектируй финансы и не открывай `MenuBuilder`.

## Реализация

1. Выполни contract gate; Agent/IoT compatibility из входа неизменяема.
2. До кода зафиксируй локальными тестами текущую потерю/дублирование или отсутствие event-feed поведения.
3. Реализуй устойчивые `event_id`, монотонный cursor, UTC `occurred_at`, tenant/terminal/device/session/operation/correlation identifiers, event type/version и immutable payload.
4. Добавь события `device_online`, session requested/active/stop/closed/failed и command started/completed/timed_out без изменения Agent protocol.
5. Создай additive internal REST feed `after/limit`, deterministic ordering, retention/cursor semantics, idempotency и reconciliation endpoint. Service auth обязателен; чужая БД недоступна.
6. Проверь duplicate delivery, pagination, concurrent writers, cursor resume, invalid cursor, auth, schema compatibility и recovery after restart.
7. Выполни локальные checks, миграции только IoT-БД, commit/push, deploy и provider smoke.

## Выход

`H-L4D-02-IOT-v1`: `API/EVENT/DEPLOYMENT` с immutable OpenAPI/JSON Schema/examples и SHA-256, exact identifiers/events/errors/cursor rules, deployed version, rollback и consumer `L4D-03-MB`.
