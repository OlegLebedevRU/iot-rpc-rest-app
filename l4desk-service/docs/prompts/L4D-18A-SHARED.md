# L4D-18A-SHARED — Зафиксировать production-версию shared package

```yaml
prompt_id: L4D-18A-SHARED
scope_project: shared/etranprocessing_db
scope_root: D:\repo\platerra\Public\etranprocessing\shared
prompt_type: release
required_handoff_ids: [H-L4D-17F-DOCS-v1, H-L4D-04A-SHARED-v1]
output_handoff_id: H-L4D-18A-SHARED-v1
next_prompt_id: L4D-18B-PB
branch: l4desk/l4d-18a-shared
report_path: shared/docs/l4desk/handoffs/L4D-18A-SHARED-report.md
architecture_sections: [3, 5, 7, 9, 10, 14, 16, 17, 18, 19]
```

## Цель

Только в `shared/etranprocessing_db` зафиксируй финальную production-candidate package version после принятого E2E. Никаких новых моделей/поведения и миграций.

## Выполнение

1. Выполни gates; версия/metadata обязаны совпадать с accepted schema и E2E matrix.
2. На clean checkout воспроизводимо собери package, запусти полный lint/format/type/tests и сравни declarative metadata с contract `04A`.
3. Проверь provenance, dependency lock, wheel/sdist contents и отсутствие secrets/unrelated files.
4. Если package уже опубликован с теми же bytes/hash, переиспользуй его; не перезаписывай version. Если нужен новый build, bump только совместимую release version и опубликуй immutable artifact.
5. Commit/push release metadata/report; deploy отсутствует, publish в package registry обязателен. Подготовь rollback на предыдущую точную версию.

## Выход

`H-L4D-18A-SHARED-v1`: `SCHEMA/DEPLOYMENT` с exact package version/URL/SHA-256/provenance/tests/rollback и consumer `L4D-18B-PB` плюс `L4D-18E-MB`.
