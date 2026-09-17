# L4D-08B-MB — Унифицировать console/video orchestration

```yaml
prompt_id: L4D-08B-MB
scope_project: MenuBuilder
scope_root: D:\repo\platerra\Public\etranprocessing\MenuBuilder
prompt_type: full-stack-consumer
required_handoff_ids: [H-L4D-07-IOT-v1, H-L4D-08A-MEDIA-v1]
output_handoff_id: H-L4D-08B-MB-v1
next_prompt_id: L4D-09-MB
branch: l4desk/l4d-08b-mb
report_path: MenuBuilder/docs/l4desk/handoffs/L4D-08B-MB-report.md
architecture_sections: [1, 2, 3, 4, 5, 6, 8, 11, 12, 13, 16, 17]
```

## Цель

Только в `MenuBuilder` направь существующих пользователей и L4Desk profile в один backend use case и один набор console/video компонентов. Provider-код не читать.

## Реализация

1. Выполни оба gates и consumer tests по immutable API fixtures.
2. Выдели единый `RemoteSessionUseCase`: tenant access, локальная reservation/policy seam, IoT session adapter, media orchestration и compensating stop при partial failure.
3. Технический lock остаётся у IoT. Если active любая session — другая отклоняется; автоматическое переключение console↔video запрещено.
4. Тарификацию/entitlement пока не реализовывай: добавь явный policy interface с permissive legacy policy и disabled L4Desk policy flag.
5. Переиспользуй текущие React routes/player/input/console; не копируй API или компоненты. Стабилизируй error reasons/offline/readiness/start timeout/cleanup.
6. Тесты backend/frontend: old flow regression, both profiles, conflict, provider failures, compensation, auth/tenant isolation, one-session UI.
7. Checks/build, commit/push, deploy под flags, smoke старого UX и скрытого L4Desk API.

## Выход

`H-L4D-08B-MB-v1`: `API/DEPLOYMENT` с единым frontend/backend contract, policy seam, error mapping, flags, regression evidence и consumer `L4D-09-MB`.
