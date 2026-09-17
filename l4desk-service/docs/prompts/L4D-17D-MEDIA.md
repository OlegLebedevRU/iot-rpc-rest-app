# L4D-17D-MEDIA — Провести приёмку медиаконтура

```yaml
prompt_id: L4D-17D-MEDIA
scope_project: l4media
scope_root: D:\repo\platerra\Public\etranprocessing\l4media
prompt_type: acceptance
required_handoff_ids: [H-L4D-17C-IOT-v1, H-L4D-08A-MEDIA-v1, H-L4D-15C-MEDIA-v1]
output_handoff_id: H-L4D-17D-MEDIA-v1
next_prompt_id: L4D-17E-MB
branch: l4desk/l4d-17d-media
report_path: l4media/docs/l4desk/handoffs/L4D-17D-MEDIA-report.md
architecture_sections: [3, 4, 5, 8, 12, 14, 15, 16, 17]
```

## Цель

Только в `l4media` доказать deployed start/health/stop, cleanup/resource limits и media archive compatibility.

## Проверки

1. Выполни gates и сверь API/manifest artifact digests с deployed version.
2. Запусти полный local suite/config tests и provider contract fixtures: repeated start/stop, health, partial start, missing resource, timeout, restart reconciliation и concurrent/resource limits.
3. После MCP readiness выполни production-safe stream smoke на test route: start→healthy→stop→no orphan route/process/mountpoint.
4. Проверь archive deterministic fixture, dry-run, restore sample и no-purge-on-failure; реальные данные не удалять.
5. Зафиксируй latency/resource evidence и rollback. Ошибка требует corrective prompt, runtime в acceptance не менять.
6. Commit/push только acceptance report.

## Выход

`H-L4D-17D-MEDIA-v1`: `REPORT/DEPLOYMENT` с exact versions, tests/smoke/cleanup/archive evidence и consumer `L4D-17E-MB`.
