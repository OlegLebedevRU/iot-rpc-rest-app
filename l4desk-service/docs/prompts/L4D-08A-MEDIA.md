# L4D-08A-MEDIA — Укрепить on-demand media lifecycle contract

```yaml
prompt_id: L4D-08A-MEDIA
scope_project: l4media
scope_root: D:\repo\platerra\Public\etranprocessing\l4media
prompt_type: implementation-provider
required_handoff_ids: [H-L4D-07-IOT-v1, H-L4D-00G-DOCS-v1]
output_handoff_id: H-L4D-08A-MEDIA-v1
next_prompt_id: L4D-08B-MB
branch: l4desk/l4d-08a-media
report_path: l4media/docs/l4desk/handoffs/L4D-08A-MEDIA-report.md
architecture_sections: [3, 4, 5, 8, 11, 12, 15, 16, 17]
```

## Цель

Только в `l4media` укрепи idempotent start/health/stop contract для route/Janus mountpoint и cleanup. Не оркестрируй IoT session и не меняй Agent.

## Реализация

1. Выполни gates; используй session identifiers из `07` только как внешний correlation contract.
2. Реализуй additive service-auth API start/health/stop с operation/session/device ids, deterministic repeated response и explicit states/errors.
3. Обеспечь timeout, cleanup partial start, stop absent/already-stopped, process/route/mountpoint reconciliation и отсутствие orphan resources.
4. Технические timestamps/metrics должны позволять audit, но решение о тарификации отсутствует.
5. Добавь contract/integration/failure/restart/concurrency/resource-limit tests; конфигурация и секреты только через approved mechanism.
6. Выполни local checks/config tests, commit/push, deploy только media components на утверждённый host, start/health/stop smoke и rollback check.

## Выход

`H-L4D-08A-MEDIA-v1`: `API/DEPLOYMENT` с OpenAPI/examples/digests, lifecycle/errors/cleanup guarantees, versions/smoke и consumer `L4D-08B-MB`.
