# L4D-06C-MB — Реализовать terminal onboarding по принятым контрактам

```yaml
prompt_id: L4D-06C-MB
scope_project: MenuBuilder
scope_root: D:\repo\platerra\Public\etranprocessing\MenuBuilder
prompt_type: implementation-consumer
required_handoff_ids: [H-L4D-06A-PB-v1, H-L4D-06B-IOT-v1]
output_handoff_id: H-L4D-06C-MB-v1
next_prompt_id: L4D-07-IOT
branch: l4desk/l4d-06c-mb
report_path: MenuBuilder/docs/l4desk/handoffs/L4D-06C-MB-report.md
architecture_sections: [1, 2, 3, 4, 5, 6, 7, 11, 13, 14, 16, 17]
```

## Цель

Только в `MenuBuilder` реализуй единый terminal onboarding consumer двух опубликованных provider contracts. Provider repositories не читать.

## Реализация

1. Выполни оба gates, сверь identifier mapping и deployment status. Любое расхождение — blocker.
2. В одной локальной транзакции создай business terminal с monotonic tenant order; самый ранний существующий terminal получает free marker, при удалении льгота переходит к следующему без ретро-пересчёта.
3. Реализуй saga/outbox: idempotent IoT provisioning и PIN request после commit, retry/reconciliation, exact readiness states и correlation.
4. Не показывай PIN повторно сверх разрешённой provider semantics; не сохраняй секрет в audit/log.
5. UI настроек показывает create, PIN delivery, Agent release link и четыре readiness: record/certificate/IoT/online. Старый terminal flow не дублировать.
6. Тесты: tenant isolation, ordering/deletion, partial provider failures, retry, duplicate clicks, provider fixtures, auth и frontend states.
7. Выполни checks/build, commit/push, deploy под feature flag и consumer smoke against deployed endpoints.

## Выход

`H-L4D-06C-MB-v1`: `API/DEPLOYMENT` с terminal lifecycle/readiness/API UI, identifier map, retries, flags, tests и consumer `L4D-07-IOT`.
