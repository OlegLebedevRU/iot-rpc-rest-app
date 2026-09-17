# L4D-03-MB — Подключить IoT Contract Consumer v1

```yaml
prompt_id: L4D-03-MB
scope_project: MenuBuilder
scope_root: D:\repo\platerra\Public\etranprocessing\MenuBuilder
prompt_type: implementation-consumer
required_handoff_ids: [H-L4D-02-IOT-v1]
output_handoff_id: H-L4D-03-MB-v1
next_prompt_id: L4D-04A-SHARED
branch: l4desk/l4d-03-mb
report_path: MenuBuilder/docs/l4desk/handoffs/L4D-03-MB-report.md
architecture_sections: [3, 4, 5, 6, 11, 12, 15, 16, 17]
```

## Цель

Только в `MenuBuilder` реализуй consumer принятого IoT event-feed contract без финансовой политики. IoT repository/RabbitMQ/MQTT не читать.

## Реализация

1. Выполни contract gate и проверь digest OpenAPI/schema/examples `02`.
2. Добавь versioned async client, service auth/config без секретных default, bounded retries/timeouts и явную error mapping строго по контракту.
3. Реализуй cursor checkpoint, идемпотентный inbox по `event_id`, транзакционную обработку, quarantine только для контрактно определённых ошибок и наблюдаемость lag.
4. На этом шаге не создавай начисления, entitlement или альтернативные session state; сохраняй только необходимые технические projections/inbox.
5. Добавь consumer contract tests по immutable fixtures: duplicate page/event, resume, empty feed, pagination, out-of-order rejection, auth/timeout и restart.
6. Выполни backend checks/tests, commit/push, deploy dark consumer с выключенным либо shadow flag и smoke без влияния на пользователей.

## Выход

`H-L4D-03-MB-v1`: `DEPLOYMENT/REPORT` с consumed contract version/digests, storage/checkpoint semantics, flags, tests, deployed commit, rollback и consumer `L4D-04A-SHARED`.
