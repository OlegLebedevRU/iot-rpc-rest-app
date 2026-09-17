# L4D-15C-MEDIA — Реализовать архив media technical details

```yaml
prompt_id: L4D-15C-MEDIA
scope_project: l4media
scope_root: D:\repo\platerra\Public\etranprocessing\l4media
prompt_type: archive-implementation
required_handoff_ids: [H-L4D-15A-DOCS-v1, H-L4D-15B-IOT-v1, H-L4D-08A-MEDIA-v1]
output_handoff_id: H-L4D-15C-MEDIA-v1
next_prompt_id: L4D-16-MB
branch: l4desk/l4d-15c-media
report_path: l4media/docs/l4desk/handoffs/L4D-15C-MEDIA-report.md
architecture_sections: [3, 5, 8, 12, 14, 15, 16, 17]
```

## Цель

Только в `l4media` реализуй архив media samples/events по общему manifest contract. IoT handoff `15B` — sequence/evidence совместимости формата, а не код для копирования.

## Реализация

1. Выполни gates и exact schema/fixture validation.
2. Архивируй только owned high-volume technical samples/events старше трёх полных месяцев; route/session summary и данные, нужные active/reconciliation, остаются hot.
3. Реализуй тот же deterministic temp→manifest/hash→reread/restore→atomic rename→verified→purge lifecycle с собственным project owner.
4. Учитывай active streams, partial media files, process cleanup, volume errors, retries и no-purge on any mismatch.
5. Добавь restore tooling/test и проверку трёхлетнего retention/backup visibility без удаления реальных архивов.
6. Выполни local tests/config checks, commit/push, deploy disabled worker, dry-run/approved batch smoke и rollback readiness.

## Выход

`H-L4D-15C-MEDIA-v1`: `DEPLOYMENT/REPORT` с manifest compatibility, record types, verification/restore/purge evidence, flags и consumer `L4D-16-MB`.
