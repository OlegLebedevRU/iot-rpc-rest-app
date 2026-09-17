# L4D-01B-IOT — Реализовать provider совместимости Agent Contract v1

```yaml
prompt_id: L4D-01B-IOT
scope_project: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
prompt_type: implementation-provider
required_handoff_ids: [H-L4D-01A-TOOLS-v1]
output_handoff_id: H-L4D-01B-IOT-v1
next_prompt_id: L4D-01C-DOCS
branch: l4desk/l4d-01b-iot
report_path: docs/l4desk/handoffs/L4D-01B-IOT-report.md
architecture_sections: [3, 4, 5, 11, 12, 16, 17]
```

## Цель

Только в `iot-rpc-rest-app` реализуй или закрепи provider adapter, полностью совместимый с фактическим `Agent Compatibility Contract v1`. Исходники `tools` не открывать.

## Реализация

1. Выполни contract gate и проверь digest golden fixtures.
2. До изменений запусти fixtures против текущего provider и зафиксируй результат. Для дефектов сначала добавь regression test.
3. Реализуй минимальный adapter/validation/capability handling, не меняя Agent topics, method codes и обязательный payload.
4. Коммерческие поля не передавай Агенту. Не создавай новый MQTT client; если изменение клиента неизбежно и тип не зафиксирован, `BLOCKED_CONTRACT`.
5. Обеспечь provider contract, duplicate/retry, unknown capability, timeout/error tests и backward compatibility текущего release.
6. Выполни локальные checks, commit/push, deploy IoT по его runbook и production-compatible contract smoke.

## Выход

`H-L4D-01B-IOT-v1`: `DEPLOYMENT/FIXTURES` с provider version, supported Agent versions, exact adapter behavior, tests, deployed image/commit, rollback и consumer `L4D-01C-DOCS`.
