# L4D-09-MB — Реализовать финансовое ядро двойной записи

```yaml
prompt_id: L4D-09-MB
scope_project: MenuBuilder
scope_root: D:\repo\platerra\Public\etranprocessing\MenuBuilder
prompt_type: financial-core-implementation
required_handoff_ids: [H-L4D-08B-MB-v1, H-L4D-04C-MB-v1]
output_handoff_id: H-L4D-09-MB-v1
next_prompt_id: L4D-10-MB
branch: l4desk/l4d-09-mb
report_path: MenuBuilder/docs/l4desk/handoffs/L4D-09-MB-report.md
architecture_sections: [3, 5, 7, 9, 10, 13, 14, 15, 16, 17]
```

## Цель

Только в `MenuBuilder` реализуй минимальный операционный `fin_*` subledger двойной записи и быструю проекцию баланса. Usage, тарифы и платежный provider пока не реализовывать.

## Реализация

1. Выполни gates и используй только deployed schema/package pair.
2. Реализуй `fin_accounts`, immutable transaction/document и entries, posting service, tenant settlement, revenue/clearing accounts, reversal/correction со ссылкой на original.
3. Каждая проведённая transaction обязана иметь `sum(debit)=sum(credit)>0`, integer kopecks, idempotency/source key, actor/correlation/timestamps. `float`, update/delete posted rows запрещены.
4. Обновляй `fin_balance_projection` инкрементально в той же DB transaction с optimistic/version protection. Источник истины — ledger; projection восстанавливаема.
5. Округление выполняется до posting. Ledger получает только `posted_kopecks`; calculated/discarded появятся в usage document, не в entries.
6. Добавь reconciliation: ledger balance, projection rebuild, duplicate posting, concurrent operations, reversal invariants, tenant isolation и corruption detection.
7. Deploy dark без пользовательских начислений, checks/tests, commit/push, smoke на synthetic transaction с обязательным rollback/reversal.

## Выход

`H-L4D-09-MB-v1`: `SCHEMA/API/DEPLOYMENT` с account/posting/reversal contract, invariants/tests, projection rules, flags, deployed version и consumer `L4D-10-MB`.
