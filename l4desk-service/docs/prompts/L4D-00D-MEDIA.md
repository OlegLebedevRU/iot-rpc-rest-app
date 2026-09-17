# L4D-00D-MEDIA — Зафиксировать baseline медиаконтура

```yaml
prompt_id: L4D-00D-MEDIA
scope_project: l4media
scope_root: D:\repo\platerra\Public\etranprocessing\l4media
prompt_type: baseline
required_handoff_ids: [H-L4D-00C-PB-v1]
output_handoff_id: H-L4D-00D-MEDIA-v1
next_prompt_id: L4D-00E-MB
branch: l4desk/l4d-00d-media
report_path: l4media/docs/l4desk/handoffs/L4D-00D-MEDIA-report.md
architecture_sections: [3, 4, 5, 8, 12, 15, 16, 17]
```

## Цель

Только в `l4media` зафиксируй baseline mTLS ingress, Janus/routes/mountpoints, on-demand stream lifecycle, health/stop, cleanup и ресурсные ограничения. Не открывай orchestrator-код `MenuBuilder` или IoT.

## Задачи

1. Выполни contract gate; вход `00C` — sequence gate.
2. Опиши фактические public/internal interfaces, identifiers, auth, state transitions, timeout, retry/idempotency и observability.
3. Зафиксируй deployed components/config/image versions без раскрытия секретов.
4. Запусти project-local tests/build/config validation и безопасный read-only/isolated smoke по runbook.
5. Не меняй runtime. Выдели пробелы для idempotent start/health/stop и архивирования деталей.
6. Commit/push только baseline report и immutable contract snapshots текущего scope.

## Выход

`H-L4D-00D-MEDIA-v1`: `REPORT` с API/lifecycle inventory, deployment state, test evidence, resource/cleanup risks и consumer `L4D-00E-MB`.
