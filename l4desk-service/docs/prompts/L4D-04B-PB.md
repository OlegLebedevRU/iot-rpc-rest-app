# L4D-04B-PB — Добавить Alembic expand-миграцию L4Desk и fin_*

```yaml
prompt_id: L4D-04B-PB
scope_project: ProcessingBackend
scope_root: D:\repo\platerra\Public\etranprocessing\ProcessingBackend
prompt_type: schema-migration-provider
required_handoff_ids: [H-L4D-04A-SHARED-v1]
output_handoff_id: H-L4D-04B-PB-v1
next_prompt_id: L4D-04C-MB
branch: l4desk/l4d-04b-pb
report_path: ProcessingBackend/docs/l4desk/handoffs/L4D-04B-PB-report.md
architecture_sections: [3, 5, 6, 7, 9, 10, 14, 16, 17]
```

## Цель

Только в `ProcessingBackend` как единственном владельце Alembic создай недеструктивную expand migration строго по принятому model contract `04A`. Shared/MenuBuilder-код не открывать.

## Реализация

1. Выполни contract gate, установи ровно переданную package/schema version и проверь digest.
2. Создай линейную миграцию от фактического head; имена, типы, defaults, constraints/indexes должны совпасть с artifact `04A`.
3. Не добавляй application behavior. Не делай backfill, `NOT NULL` contract phase, drop/rename или активацию feature.
4. Добавь schema tests: clean upgrade, upgrade existing DB, metadata diff, downgrade на тестовой БД, repeated deployment safety и constraint checks.
5. Выполни ruff/format/pyright/pytest и migration checks; commit/push.
6. Проведи MCP readiness, затем deploy только migration на утверждённый host; проверь Alembic head/schema и rollback readiness. Перезапусти зависимый backend только если это требует runbook.

## Выход

`H-L4D-04B-PB-v1`: `SCHEMA/DEPLOYMENT` с input package digest, Alembic revision/down_revision, DDL snapshot/hash, deployed head, tests/rollback и consumer `L4D-04C-MB`.
