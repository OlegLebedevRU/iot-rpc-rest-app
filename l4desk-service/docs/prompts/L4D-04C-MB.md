# L4D-04C-MB — Подключить совместимую expand-схему L4Desk

```yaml
prompt_id: L4D-04C-MB
scope_project: MenuBuilder
scope_root: D:\repo\platerra\Public\etranprocessing\MenuBuilder
prompt_type: schema-consumer
required_handoff_ids: [H-L4D-04A-SHARED-v1, H-L4D-04B-PB-v1]
output_handoff_id: H-L4D-04C-MB-v1
next_prompt_id: L4D-05-MB
branch: l4desk/l4d-04c-mb
report_path: MenuBuilder/docs/l4desk/handoffs/L4D-04C-MB-report.md
architecture_sections: [3, 5, 6, 7, 9, 10, 14, 16, 17]
```

## Цель

Только в `MenuBuilder` подключи опубликованный shared package и доказанно deployed expand schema в тёмном режиме. Не создавай миграцию и не меняй shared package.

## Реализация

1. Выполни оба contract gate и сверь package digest с deployed Alembic revision.
2. Обнови dependency lock только до принятой версии. Добавь startup/schema compatibility check без автоматического DDL.
3. Подключи модели/репозитории настолько, насколько нужно для последующих шагов, но не активируй регистрацию, billing или UI.
4. Добавь compatibility tests against migrated DB, import/model mapping, absent optional columns during rolling deploy и startup error on wrong revision.
5. Выполни backend lint/type/tests; frontend не меняй. Commit/push, deploy dark code и smoke с flags disabled.

## Выход

`H-L4D-04C-MB-v1`: `DEPLOYMENT/SCHEMA` с package/revision pair, flags, compatibility tests, deployed backend version, rollback и consumer `L4D-05-MB`.
