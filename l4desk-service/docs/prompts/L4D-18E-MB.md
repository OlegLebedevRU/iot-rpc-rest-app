# L4D-18E-MB — Активировать production-функции L4Desk

```yaml
prompt_id: L4D-18E-MB
scope_project: MenuBuilder
scope_root: D:\repo\platerra\Public\etranprocessing\MenuBuilder
prompt_type: production-rollout
required_handoff_ids: [H-L4D-18D-MEDIA-v1, H-L4D-18B-PB-v1, H-L4D-18C-IOT-v1, H-L4D-18A-SHARED-v1, H-L4D-17F-DOCS-v1, H-L4D-17E-MB-v1]
output_handoff_id: H-L4D-18E-MB-v1
next_prompt_id: L4D-18F-DOCS
branch: l4desk/l4d-18e-mb
report_path: MenuBuilder/docs/l4desk/handoffs/L4D-18E-MB-report.md
architecture_sections: [1, 2, 3, 4, 5, 6, 7, 9, 10, 13, 14, 15, 16, 17, 18, 19]
```

## Цель

Только в `MenuBuilder` разверни и последовательно активируй L4Desk commercial/UX functions поверх уже принятых provider deployments.

## Выполнение

1. Выполни все gates; deployed provider versions/endpoints и shared package/schema должны совпадать дословно. Не открывай provider repos.
2. Полный backend/frontend suite, consumer fixtures, lint/type/build; build immutable backend image и SPA. Commit/push release.
3. Проведи MCP readiness. Deploy backend и frontend artifacts только на `87.242.100.34` по runbook; migrations не создавать/применять вне принятого PB head.
4. Проверяй после deploy schema compatibility и flags disabled. Затем включай поэтапно: internal consumers/shadow metering → registration/onboarding restricted → payment → entitlement → profile/Hub. Между фазами smoke и rollback checkpoint.
5. Smoke test tenant: registration/terminal/PIN/readiness, one console/video, positive paid continuation after 120 min, terminal-month, payment idempotency, ledger/reconciliation zero mismatch, grace/block/stop, Hub/archive status.
6. Проверь старого user и текущий Agent; исключи массовые email/real unintended charges. Любой финансовый mismatch требует немедленно выключить commercial flags и rollback.
7. Создай exact deployment report с running versions/flags/timestamps/evidence.

## Выход

`H-L4D-18E-MB-v1`: `DEPLOYMENT` с production backend/frontend/shared/schema/providers matrix, activation timeline, financial invariants, smoke/rollback и consumer `L4D-18F-DOCS`.
