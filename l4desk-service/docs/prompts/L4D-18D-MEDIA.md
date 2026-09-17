# L4D-18D-MEDIA — Выполнить финальный production rollout l4media

```yaml
prompt_id: L4D-18D-MEDIA
scope_project: l4media
scope_root: D:\repo\platerra\Public\etranprocessing\l4media
prompt_type: production-rollout
required_handoff_ids: [H-L4D-18C-IOT-v1, H-L4D-17D-MEDIA-v1, H-L4D-08A-MEDIA-v1, H-L4D-15C-MEDIA-v1]
output_handoff_id: H-L4D-18D-MEDIA-v1
next_prompt_id: L4D-18E-MB
branch: l4desk/l4d-18d-media
report_path: l4media/docs/l4desk/handoffs/L4D-18D-MEDIA-report.md
architecture_sections: [3, 4, 5, 8, 12, 14, 15, 16, 17, 18, 19]
```

## Цель

Только в `l4media` разверни принятый media lifecycle/archive release, сохранив существующие streams и совместимость orchestration contract.

## Выполнение

1. Выполни gates, сверь exact API/manifest/image/config versions.
2. Запусти полный project-local tests/build/config validation, commit/push immutable release.
3. Проведи MCP readiness и deploy только l4media components на `87.242.100.34` по runbook; не перезапускай чужие containers.
4. Archive purge оставь disabled; mounted volume/permissions/backup readiness проверь безопасно.
5. Production smoke test route: idempotent start→health→stop, partial/repeated stop, cleanup no orphan, resource metrics и archive dry-run/restore sample.
6. При failure project-local rollback; зафиксируй реально работающие versions и flags.

## Выход

`H-L4D-18D-MEDIA-v1`: `DEPLOYMENT` с production versions/config digest, stream/archive smoke, metrics/rollback и consumer `L4D-18E-MB`.
