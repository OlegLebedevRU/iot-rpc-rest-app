# L4D-00B-IOT — Зафиксировать baseline device/RPC-контура

```yaml
prompt_id: L4D-00B-IOT
scope_project: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
prompt_type: baseline
required_handoff_ids: [H-L4D-00A-TOOLS-v1]
output_handoff_id: H-L4D-00B-IOT-v1
next_prompt_id: L4D-00C-PB
branch: l4desk/l4d-00b-iot
report_path: docs/l4desk/handoffs/L4D-00B-IOT-report.md
architecture_sections: [3, 4, 5, 11, 12, 15, 17]
```

## Цель

Только в `iot-rpc-rest-app` зафиксируй production-compatible baseline реестра устройств, RabbitMQ/MQTT, RPC, remote input, текущего API и alpha billing. `H-L4D-00A-TOOLS-v1` используется как immutable внешний Agent baseline; исходники `tools` не открывать.

## Обязательная работа

1. Выполни contract gate и сверь digest всех входных Agent fixtures.
2. Инвентаризируй device identifiers, presence, topics/queues, RPC `tsk/req/rsp/res/cmt`, idempotency, session/lease state, API/OpenAPI, migrations, workers и deployment version.
3. Проверь фактическую совместимость текущего provider с принятыми golden fixtures локальными тестами; не исправляй контракт и не меняй runtime в baseline-шаге.
4. Отдельно опиши alpha billing как предположение для переиспользования, но не как финансовый источник истины.
5. Зафиксируй пробелы: durable event ids/feed, provisioning, mutual exclusion, graceful stop, archival readiness.
6. Выполни локальные lint/type/test/build и read-only production probes по runbook. Создай/запушь только отчёт и baseline artifacts текущего проекта.

## Выход

`H-L4D-00B-IOT-v1`: `REPORT` с commit/image/schema/API versions, topology inventory без секретов, Agent fixture test results, deploy evidence, gaps и consumer `L4D-00C-PB` как sequence gate. Не заявляй семантику, которой нет в коде/тестах.
