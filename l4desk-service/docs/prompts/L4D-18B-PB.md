# L4D-18B-PB — Выполнить финальный production rollout ProcessingBackend

```yaml
prompt_id: L4D-18B-PB
scope_project: ProcessingBackend
scope_root: D:\repo\platerra\Public\etranprocessing\ProcessingBackend
prompt_type: production-rollout
required_handoff_ids: [H-L4D-18A-SHARED-v1, H-L4D-17B-PB-v1, H-L4D-04B-PB-v1, H-L4D-06A-PB-v1]
output_handoff_id: H-L4D-18B-PB-v1
next_prompt_id: L4D-18C-IOT
branch: l4desk/l4d-18b-pb
report_path: ProcessingBackend/docs/l4desk/handoffs/L4D-18B-PB-report.md
architecture_sections: [3, 4, 5, 7, 14, 15, 16, 17, 18, 19]
```

## Цель

Только в `ProcessingBackend` выполнить финальный совместимый rollout package/schema/certificate provider на утверждённый production host.

## Выполнение

1. Выполни gates; сверь exact shared package, image/commit, Alembic revision и API contract. Любое различие блокирует rollout.
2. До deploy запусти полный project suite/lint/type и build immutable image/artifact. Commit/push только release files/report текущего scope.
3. Проведи MCP readiness; при degraded используй штатный SSH `user1@87.242.100.34` с `-n`, не другой host.
4. Выполни backup/readiness, deploy additive release и `alembic upgrade` до точного revision. Destructive contract phase запрещена.
5. Проверь running image/commit/head, health, old terminal certificate flow и provider PIN contract smoke. Не раскрывай secrets/PIN.
6. При ошибке остановись и выполни заранее проверенный project-local rollback, не меняя соседние services.
7. Создай deployment report, commit/push его при необходимости по runbook.

## Выход

`H-L4D-18B-PB-v1`: `DEPLOYMENT` с exact production image/commit/package/head, command/smoke evidence, rollback status и consumer `L4D-18C-IOT` плюс `L4D-18E-MB`.
