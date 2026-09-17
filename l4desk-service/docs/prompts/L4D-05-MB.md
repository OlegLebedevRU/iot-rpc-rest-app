# L4D-05-MB — Реализовать саморегистрацию и email confirmation

```yaml
prompt_id: L4D-05-MB
scope_project: MenuBuilder
scope_root: D:\repo\platerra\Public\etranprocessing\MenuBuilder
prompt_type: full-stack-implementation
required_handoff_ids: [H-L4D-04C-MB-v1]
output_handoff_id: H-L4D-05-MB-v1
next_prompt_id: L4D-06A-PB
branch: l4desk/l4d-05-mb
report_path: MenuBuilder/docs/l4desk/handoffs/L4D-05-MB-report.md
architecture_sections: [1, 2, 3, 4, 5, 6, 13, 14, 16, 17]
```

## Цель

Только в `MenuBuilder` реализуй публичную саморегистрацию L4Desk, подтверждение email и атомарное создание user `role=5` + tenant + owner membership.

## Реализация

1. Выполни contract gate. Сохрани существующие auth flows и tenant users.
2. Реализуй registration state, нормализацию/уникальность email, безопасный short-lived one-time verification token, resend/rate limits и generic anti-enumeration responses.
3. После подтверждения в одной транзакции создай user role 5, tenant, owner membership, timezone и immutable audit. Повтор подтверждения идемпотентен.
4. До первой оплаты доступен только бесплатный пакет; платежи и terminal provisioning здесь не реализовывать.
5. Добавь backend и frontend UX под feature flag: success/expired/used/conflict/race, accessibility и безопасный return URL.
6. Тесты: core/negative/edge/race/replay, JWT `org_id` boundary, tenant isolation, email delivery adapter; frontend build/tests.
7. Выполни все MenuBuilder checks, commit/push, deploy backend+SPA только этого scope, smoke под выключенным/ограниченным flag.

## Выход

`H-L4D-05-MB-v1`: `API/DEPLOYMENT` с registration API/UI contract, states/errors/audit, flags, tests, deployed versions и consumer `L4D-06A-PB`.
