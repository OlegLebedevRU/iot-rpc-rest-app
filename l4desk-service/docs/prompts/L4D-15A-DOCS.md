# L4D-15A-DOCS — Опубликовать общий Archive Manifest Contract

```yaml
prompt_id: L4D-15A-DOCS
scope_project: l4desk-service
scope_root: D:\repo\platerra\Public\etranprocessing\l4desk-service
prompt_type: contract-governance
required_handoff_ids: [H-L4D-14-MB-v1]
output_handoff_id: H-L4D-15A-DOCS-v1
next_prompt_id: L4D-15B-IOT
branch: l4desk/l4d-15a-docs
report_path: l4desk-service/docs/handoffs/L4D-15A-DOCS-report.md
architecture_sections: [3, 5, 6, 7, 10, 14, 15, 16, 17, 18]
```

## Цель

Только в `l4desk-service` опубликуй общий immutable Archive Manifest Contract для независимой реализации IoT и media. Runtime repositories не открывать.

## Контракт

1. Выполни gate и используй archive identifiers из принятого Hub handoff.
2. Определи `archive_batch_id`, owner project, UTC creation, source calendar month/time range, schema/version, record types/counts, min/max timestamps/cursors, file list/size/SHA-256, compression, state `prepared/verified/purged/failed`, verification/purge timestamps и error.
3. Layout mounted volume: `<root>/<year>/<month>/<project>/<archive_batch_id>/`; temporary directory и atomic final rename.
4. Формат MVP — deterministic UTF-8 `JSONL.gz` плюс `manifest.json` и checksum. Определи canonical serialization и fixtures.
5. Purge разрешён только после full reread, counts/hash verification, successful restore sample и consumer cursor выше archive boundary. Financial ядро/aggregates/session summary не входят в mass purge.
6. Hot details — 3 полных месяца; финансовая и техническая архивная история — минимум 3 года; mounted volume входит в backup.
7. Создай JSON Schema/examples/acceptance vectors, проверь их валидатором, commit/push и добавь accepted handoff в единый журнал.

## Выход

`H-L4D-15A-DOCS-v1`: `SCHEMA/FIXTURES` с files/digests, canonical rules/retention/cursor guard и consumers `L4D-15B-IOT`, `L4D-15C-MEDIA`, `L4D-16-MB`.
