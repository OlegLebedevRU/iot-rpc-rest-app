# L4D-13-MB — Реализовать frontend profile и onboarding UX

```yaml
prompt_id: L4D-13-MB
scope_project: MenuBuilder
scope_root: D:\repo\platerra\Public\etranprocessing\MenuBuilder
prompt_type: frontend-full-stack
required_handoff_ids: [H-L4D-12-MB-v1, H-L4D-06C-MB-v1, H-L4D-08B-MB-v1]
output_handoff_id: H-L4D-13-MB-v1
next_prompt_id: L4D-14-MB
branch: l4desk/l4d-13-mb
report_path: MenuBuilder/docs/l4desk/handoffs/L4D-13-MB-report.md
architecture_sections: [1, 2, 3, 4, 5, 6, 9, 13, 14, 16, 17]
```

## Цель

Только в одной SPA/ backend `MenuBuilder` создай L4Desk navigation profile и понятный onboarding/лицензионный UX без копий console/video компонентов.

## Реализация

1. Выполни gates и используй только принятые API/reason codes.
2. Добавь пять разделов: «Видеонаблюдение», «Настройки» (Профиль/Терминалы/Пользователи), «Консоль», «MCP», «Лицензии».
3. Мастер: create terminal → PIN → ссылка на последний существующий Agent release → install instruction → readiness/online → открыть одну console/video session.
4. Покажи причины отказа отдельно: session conflict, offline, provisioning/certificate pending, free quota exhausted without paid access, grace/blocked.
5. Licenses UX: balance/top-up, next renewal, active/grace/blocked, remaining grace, today pooled free/paid use, explainable charge rows, warnings. Положительный balance явно разрешает платное продолжение после 120 минут.
6. MCP — promo/waitlist с tenant и выбранным use case, без remote tools. Existing user profile остаётся рабочим.
7. Добавь accessibility/responsive/error/loading tests, route/role/tenant tests и reuse assertions; backend tests и production frontend build.
8. Commit/push, deploy SPA/backend под L4Desk feature profile, smoke старого и нового navigation без глобальной активации.

## Выход

`H-L4D-13-MB-v1`: `API/DEPLOYMENT` с routes/components/API consumption, UX states/reasons, flags, build/test evidence и consumer `L4D-14-MB`.
