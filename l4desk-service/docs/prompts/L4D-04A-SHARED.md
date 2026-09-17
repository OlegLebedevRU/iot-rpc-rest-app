# L4D-04A-SHARED — Добавить declarative expand-модели L4Desk и fin_*

```yaml
prompt_id: L4D-04A-SHARED
scope_project: shared/etranprocessing_db
scope_root: D:\repo\platerra\Public\etranprocessing\shared
prompt_type: schema-model-provider
required_handoff_ids: [H-L4D-03-MB-v1]
output_handoff_id: H-L4D-04A-SHARED-v1
next_prompt_id: L4D-04B-PB
branch: l4desk/l4d-04a-shared
report_path: shared/docs/l4desk/handoffs/L4D-04A-SHARED-report.md
architecture_sections: [3, 5, 6, 7, 9, 10, 14, 16, 17]
```

## Цель

Только в `shared/etranprocessing_db` добавь thin declarative expand-модели L4Desk и финансового контура. Не создавай Alembic migration и бизнес-логику.

## Реализация

1. Выполни contract gate; вход `03` подтверждает порядок, но не позволяет выдумывать DB schema.
2. Спроектируй минимальные модели по архитектурным инвариантам: onboarding/audit, IoT inbox/cursor, remote session summary, `fin_*` tariff/cycle/usage/monthly charge/payment/accounts/ledger/balance/notification/archive manifest.
3. Все финансовые таблицы/constraints/indexes имеют `fin_` prefix; суммы — integer kopecks; timestamps timezone-aware; внешние event ids — строки/UUID согласно принятому IoT contract.
4. Добавь PK/FK/unique/check/index metadata для idempotency, balanced transaction support и одной активной session reservation, не помещая расчёты в package.
5. Схема только expand: nullable/server defaults там, где нужен совместимый rollout; destructive changes запрещены.
6. Добавь model/package tests, запусти lint/format/type/tests/build, bump совместимой package version, commit/push/publish package.

## Выход

`H-L4D-04A-SHARED-v1`: `SCHEMA` с package version/digest, полный model/table/constraint contract, compatibility notes и consumer `L4D-04B-PB`.
