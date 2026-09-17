# L4D-18F-DOCS — Выпустить итоговый реестр версий и эксплуатационный отчёт

```yaml
prompt_id: L4D-18F-DOCS
scope_project: l4desk-service
scope_root: D:\repo\platerra\Public\etranprocessing\l4desk-service
prompt_type: release-governance
required_handoff_ids: [H-L4D-18A-SHARED-v1, H-L4D-18B-PB-v1, H-L4D-18C-IOT-v1, H-L4D-18D-MEDIA-v1, H-L4D-18E-MB-v1]
output_handoff_id: H-L4D-18F-DOCS-v1
next_prompt_id: NONE
branch: l4desk/l4d-18f-docs
report_path: l4desk-service/docs/handoffs/L4D-18F-DOCS-report.md
architecture_sections: [1, 3, 4, 5, 14, 15, 16, 17, 18, 19]
```

## Цель

Только в `l4desk-service` выпусти финальный operations handoff и закрой каскад на основании пяти фактически принятых production reports. Runtime projects/endpoints не менять.

## Выполнение

1. Выполни все gates и проверь artifact digests, commit/image/package/schema/API/Agent versions, environment и timestamps.
2. Сформируй единый deployed version matrix, contract compatibility matrix, feature flags, migrations, endpoints без secrets, owners/runbooks и rollback order.
3. Зафиксируй operational checks/alerts: registration, provisioning/PIN, device online, active sessions, event/usage lag, ledger imbalance=0, reconciliation mismatch=0, YooKassa pending/errors, grace/blocked, archive checksum.
4. Документируй backup/restore mounted archive volume, hot retention 3 full months и minimum 3-year archive/financial retention.
5. Не маскируй known risk. Любой несовпадающий report/version или незелёный smoke блокирует завершение и создаёт corrective prompt.
6. Проверь Markdown/links и полноту единого handoff journal, commit/push только `l4desk-service`.
7. Добавь финальный accepted block в журнал и отметь cascade closed без редактирования прежних blocks.

## Выход

`H-L4D-18F-DOCS-v1`: `REPORT/SEQUENCE_GATE` с `next_prompt_id: NONE`, точным production registry, эксплуатационным/rollback handoff и статусом каскада `CLOSED_ACCEPTED`.
