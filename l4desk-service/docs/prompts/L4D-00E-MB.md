# L4D-00E-MB — Зафиксировать baseline коммерческого и UX-контура

```yaml
prompt_id: L4D-00E-MB
scope_project: MenuBuilder
scope_root: D:\repo\platerra\Public\etranprocessing\MenuBuilder
prompt_type: baseline
required_handoff_ids: [H-L4D-00D-MEDIA-v1]
output_handoff_id: H-L4D-00E-MB-v1
next_prompt_id: L4D-00F-SHARED
branch: l4desk/l4d-00e-mb
report_path: MenuBuilder/docs/l4desk/handoffs/L4D-00E-MB-report.md
architecture_sections: [1, 2, 3, 4, 5, 9, 13, 14, 16, 17]
```

## Цель

Только в `MenuBuilder` зафиксируй baseline backend/frontend для tenant/users/terminals, существующих console/video flows, IoT client, billing/licensing UX, auth и deployment. Не открывай provider repositories; вход `00D` — sequence gate.

## Задачи

1. Выполни contract gate и правила обоих подпроектов `MenuBuilder`.
2. Инвентаризируй модели/API/UI routes, roles, tenant boundary, terminal ownership, current billing, IoT/media adapters, console/video components и feature flags.
3. Докажи, какие реализации могут быть едиными для старого UX и L4Desk; не создавай альтернативный flow.
4. Зафиксируй database/shared dependency versions, deployed backend/frontend commits и current tests.
5. Запусти backend lint/type/tests и frontend build/tests, относящиеся к baseline. Runtime не менять.
6. Commit/push только отчёт и snapshots текущего scope.

## Выход

`H-L4D-00E-MB-v1`: `REPORT` с API/UI/model inventory, reusable seams, gaps, checks, deploy evidence и consumer `L4D-00F-SHARED`.
