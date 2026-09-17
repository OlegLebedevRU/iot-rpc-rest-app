# L4D-11-MB — Реализовать ЮKassa и ручные оплаты

```yaml
prompt_id: L4D-11-MB
scope_project: MenuBuilder
scope_root: D:\repo\platerra\Public\etranprocessing\MenuBuilder
prompt_type: payment-implementation
required_handoff_ids: [H-L4D-10-MB-v1]
output_handoff_id: H-L4D-11-MB-v1
next_prompt_id: L4D-12-MB
branch: l4desk/l4d-11-mb
report_path: MenuBuilder/docs/l4desk/handoffs/L4D-11-MB-report.md
architecture_sections: [2, 3, 5, 7, 9, 10, 13, 14, 15, 16, 17]
```

## Цель

Только в `MenuBuilder` реализуй пополнение внутреннего баланса физлиц через ЮKassa и ручной неизменяемый документ оплаты юрлица одним superuser.

## Реализация

1. Выполни gate. Проверь актуальный официальный API ЮKassa, но не считай документацию handoff другого проекта: это внешний provider текущего scope.
2. Принимай целую положительную сумму рублей; создавай `fin_payment` и provider payment с уникальным `Idempotence-Key`, confirmation URL и безопасным return URL.
3. Return браузера не подтверждает деньги. Webhook — триггер; перед posting сервером получи payment и только `succeeded` с совпадающими amount/currency/merchant data создаёт одну ledger transaction.
4. Реализуй signature/source controls согласно ЮKassa, replay-safe webhook, fallback polling, pending/canceled, receipt/customer email snapshot и конфигурируемые fiscal items/VAT без hardcode секретов.
5. Первая успешная оплата атомарно фиксирует неизменяемый cycle anchor; поздние платежи не двигают существующий anchor.
6. Manual payment: superuser, integer rubles, occurred date, document number/payer/comment/evidence reference/audit; posting immutable, ошибка только reversal+new document.
7. Тесты provider mock/contract, duplicate webhook+poll, mismatch, timeout/unknown result, first-payment race, manual auth/storno и ledger reconciliation.
8. Checks/build, commit/push, deploy сначала sandbox/flagged production config, безопасный smoke без реального списания либо утверждённый минимальный платёж.

## Выход

`H-L4D-11-MB-v1`: `API/DEPLOYMENT` с payment state/idempotency/webhook/poll/manual/storno contract, fiscal config keys без values, tests/deploy evidence и consumer `L4D-12-MB`.
