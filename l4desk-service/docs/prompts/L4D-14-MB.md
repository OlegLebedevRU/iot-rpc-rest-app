# L4D-14-MB — Реализовать Хаб и финансовую сверку

```yaml
prompt_id: L4D-14-MB
scope_project: MenuBuilder
scope_root: D:\repo\platerra\Public\etranprocessing\MenuBuilder
prompt_type: admin-reconciliation
required_handoff_ids: [H-L4D-13-MB-v1, H-L4D-09-MB-v1, H-L4D-10-MB-v1, H-L4D-11-MB-v1, H-L4D-12-MB-v1]
output_handoff_id: H-L4D-14-MB-v1
next_prompt_id: L4D-15A-DOCS
branch: l4desk/l4d-14-mb
report_path: MenuBuilder/docs/l4desk/handoffs/L4D-14-MB-report.md
architecture_sections: [1, 2, 3, 5, 6, 7, 9, 10, 13, 14, 15, 16, 17]
```

## Цель

Только в `MenuBuilder` реализуй superuser Хаб и явные сверки `source facts → usage → ledger → balance`.

## Реализация

1. Выполни gates. Хаб читает локальные projections/inbox и принятые external identifiers, но не чужие БД.
2. Вкладки: registrations; terminals/provisioning/certificate readiness; sessions/usage; licenses/finance/payments; notifications/errors.
3. Фильтры: tenant, terminal, period, user/email, type/status, console/video, active/grace/blocked, free/paid, payment source/id, session/correlation id, only errors/unreconciled.
4. Correlation drill-down показывает фактические ссылки на registration→terminal→PIN/provisioning→online/session→usage→ledger/payment; отсутствующий факт помечается mismatch, не дорисовывается.
5. Reconciliation проверяет debit=credit, projection rebuild, calculated=posted+discarded, posted%100=0, source hash/event coverage, unique monthly charge/payment posting.
6. Manual payment/storno UI использует `11`, имеет superuser auth/audit/confirmation.
7. Тесты RBAC/data leakage, pagination/filtering, reconciliation mismatches, rounding, immutable corrections и UI states. Checks/build, commit/push, deploy restricted, smoke.

## Выход

`H-L4D-14-MB-v1`: `API/DEPLOYMENT` с Hub filters/views/reconciliation contract, mismatch codes, archive identifiers, tests и consumer `L4D-15A-DOCS`.
