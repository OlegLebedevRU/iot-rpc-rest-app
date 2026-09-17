# L4D-00F-SHARED — Зафиксировать baseline общей модели данных

```yaml
prompt_id: L4D-00F-SHARED
scope_project: shared/etranprocessing_db
scope_root: D:\repo\platerra\Public\etranprocessing\shared
prompt_type: baseline
required_handoff_ids: [H-L4D-00E-MB-v1]
output_handoff_id: H-L4D-00F-SHARED-v1
next_prompt_id: L4D-00G-DOCS
branch: l4desk/l4d-00f-shared
report_path: shared/docs/l4desk/handoffs/L4D-00F-SHARED-report.md
architecture_sections: [3, 5, 9, 10, 14, 16, 17]
```

## Цель

Только в тонком declarative package `shared/etranprocessing_db` зафиксируй модели, relationships, constraints, indexes, package metadata и checks. Бизнес-логику и Alembic сюда не добавлять.

## Задачи

1. Выполни contract gate; `00E` — sequence gate, код `MenuBuilder` не читать.
2. Инвентаризируй модели и naming conventions, импортные границы, package version/build и совместимость Python/SQLAlchemy.
3. Подтверди отсутствие framework/business/auth/crypto logic.
4. Запусти package-local lint/format/type/tests/build.
5. Runtime-модели не менять. Подготовь список безопасных expand-точек для `fin_*` без проектирования отсутствующего контракта.
6. Commit/push только baseline report текущего scope.

## Выход

`H-L4D-00F-SHARED-v1`: `REPORT` с package/model baseline, conventions, checks, version и consumer `L4D-00G-DOCS`.
