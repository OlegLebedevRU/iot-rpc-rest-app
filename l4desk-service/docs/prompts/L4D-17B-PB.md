# L4D-17B-PB — Провести приёмку certificate/PIN-контура

```yaml
prompt_id: L4D-17B-PB
scope_project: ProcessingBackend
scope_root: D:\repo\platerra\Public\etranprocessing\ProcessingBackend
prompt_type: acceptance
required_handoff_ids: [H-L4D-17A-TOOLS-v1, H-L4D-06A-PB-v1, H-L4D-04B-PB-v1]
output_handoff_id: H-L4D-17B-PB-v1
next_prompt_id: L4D-17C-IOT
branch: l4desk/l4d-17b-pb
report_path: ProcessingBackend/docs/l4desk/handoffs/L4D-17B-PB-report.md
architecture_sections: [3, 4, 5, 7, 14, 15, 16, 17]
```

## Цель

Только в `ProcessingBackend` докажи готовность deployed certificate/PIN provider и schema. Не запускай onboarding из `MenuBuilder` и не открывай Agent source.

## Проверки

1. Выполни gates; сверь production image/commit, Alembic head и API version с handoff.
2. Запусти полный project-local suite/lint/type и provider contract fixtures для create/repeat/conflict/expired/used/replay/CSR binding/auth.
3. После MCP readiness выполни безопасный production smoke на выделенных test identifiers; не раскрывай PIN/credentials в evidence и очисти созданные test records только штатным lifecycle.
4. Подтверди backward compatibility terminal-facing certificate API и отсутствие незаявленных migrations.
5. Любой mismatch создаёт corrective prompt; acceptance-код не меняй. Commit/push только отчёт, если исправление не потребовалось.

## Выход

`H-L4D-17B-PB-v1`: `REPORT/DEPLOYMENT` с exact versions/head, tests/provider probes, redacted smoke, rollback readiness и consumer `L4D-17C-IOT`.
