# L4D-17E-MB — Провести приёмку коммерческого контура

```yaml
prompt_id: L4D-17E-MB
scope_project: MenuBuilder
scope_root: D:\repo\platerra\Public\etranprocessing\MenuBuilder
prompt_type: acceptance
required_handoff_ids: [H-L4D-17D-MEDIA-v1, H-L4D-06C-MB-v1, H-L4D-08B-MB-v1, H-L4D-09-MB-v1, H-L4D-10-MB-v1, H-L4D-11-MB-v1, H-L4D-12-MB-v1, H-L4D-13-MB-v1, H-L4D-14-MB-v1, H-L4D-16-MB-v1]
output_handoff_id: H-L4D-17E-MB-v1
next_prompt_id: L4D-17F-DOCS
branch: l4desk/l4d-17e-mb
report_path: MenuBuilder/docs/l4desk/handoffs/L4D-17E-MB-report.md
architecture_sections: [1, 2, 3, 4, 5, 6, 7, 9, 10, 13, 14, 15, 16, 17]
```

## Цель

Только в `MenuBuilder` провести полную project-local и consumer-contract приёмку L4Desk commercial control plane без глобальной production activation.

## Проверки

1. Выполни все gates; deployed provider reports используются как внешнее evidence, provider-код не открывать.
2. Полный backend/frontend suite, lint/type/build и immutable consumer fixtures.
3. Сценарии: registration/email/user+tenant; terminal/readiness; unified old/new console/video; mutual exclusion; no-payment free terminal+120 min; positive-balance paid continuation; first payment anchor; terminal-month online once; DST/month boundaries; grace and late online/payment; graceful block.
4. Проверь ЮKassa mock/sandbox webhook+poll idempotency, manual payment/storno, double-entry/rebuild, rounding/discarded post-reconciliation, Hub filters/correlation/mismatch и archive manifest import/retention.
5. Production-safe smoke только с disabled/restricted flags и test tenant; никаких реальных массовых email/charges.
6. Зафиксируй zero ledger imbalance/reconciliation mismatch, versions/flags/rollback. Defect — corrective prompt, не скрытое исправление.
7. Commit/push acceptance report.

## Выход

`H-L4D-17E-MB-v1`: `REPORT/DEPLOYMENT` с commercial verdict, full test matrix, exact versions/flags/financial invariants и consumer `L4D-17F-DOCS`.
