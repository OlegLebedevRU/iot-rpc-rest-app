# L4D-12-MB — Реализовать entitlement, grace и уведомления

```yaml
prompt_id: L4D-12-MB
scope_project: MenuBuilder
scope_root: D:\repo\platerra\Public\etranprocessing\MenuBuilder
prompt_type: entitlement-implementation
required_handoff_ids: [H-L4D-11-MB-v1, H-L4D-10-MB-v1, H-L4D-07-IOT-v1, H-L4D-08B-MB-v1]
output_handoff_id: H-L4D-12-MB-v1
next_prompt_id: L4D-13-MB
branch: l4desk/l4d-12-mb
report_path: MenuBuilder/docs/l4desk/handoffs/L4D-12-MB-report.md
architecture_sections: [2, 3, 5, 6, 8, 9, 10, 13, 14, 15, 16, 17]
```

## Цель

Только в `MenuBuilder` реализуй коммерческое решение start/continue/stop, cycle-bound grace и идемпотентные email notifications. IoT исполняет stop по принятому contract.

## Нормативная логика

1. До первой успешной оплаты доступны только free terminal и его pooled `120 min/local day`; grace отсутствует. При положительном балансе после квоты работа продолжается платно.
2. После первой оплаты status определяется balance и границей cycle: `active` при balance≥0; `grace` при balance<0 и `now < cycle_start+3 days`; `blocked` иначе.
3. Grace всегда привязан к cycle boundary, не к online/charge/payment. Online на пятый день создаёт charge текущего cycle и при недостатке средств немедленно blocked.
4. Поздняя оплата погашает текущий период и не переносит anchor. Возврат balance≥0 разблокирует.
5. При blocked новые sessions запрещены. Active video/remote stop при периодической проверке; console запрещает новые commands, ждёт текущий response или IoT timeout, затем stop.
6. Уведомления `renewal-7d/-3d/-1d`, `grace_started`, `blocked` уникальны по tenant/cycle/type; retry не создаёт дубль.

## Работа и проверки

Подключи policy seam `08B`, готовую balance projection, periodic worker с умеренным интервалом, reason codes/API status и stop outbox/retry. Тестируй no-payment free quota, positive paid continuation, all cycle/grace boundaries, online after deadline, late payment, active session stop, email idempotency/timezone/DST и provider failures. Выполни checks/build, commit/push, deploy disabled/shadow policy и smoke.

## Выход

`H-L4D-12-MB-v1`: `API/DEPLOYMENT` с entitlement state machine/reason codes/notification/stop rules, flags, tests и consumer `L4D-13-MB`.
