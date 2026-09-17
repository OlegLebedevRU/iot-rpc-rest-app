# L4D-06A-PB — Опубликовать идемпотентный Certificate PIN Contract

```yaml
prompt_id: L4D-06A-PB
scope_project: ProcessingBackend
scope_root: D:\repo\platerra\Public\etranprocessing\ProcessingBackend
prompt_type: implementation-provider
required_handoff_ids: [H-L4D-05-MB-v1, H-L4D-00G-DOCS-v1]
output_handoff_id: H-L4D-06A-PB-v1
next_prompt_id: L4D-06B-IOT
branch: l4desk/l4d-06a-pb
report_path: ProcessingBackend/docs/l4desk/handoffs/L4D-06A-PB-report.md
architecture_sections: [3, 4, 5, 7, 11, 14, 16, 17]
```

## Цель

Только в `ProcessingBackend` опубликуй additive service contract для идемпотентного выпуска certificate PIN и последующего CSR/X.509 flow. Не реализуй terminal onboarding `MenuBuilder`.

## Реализация

1. Выполни contract gates: `05` — sequence, `00G` — принятый certificate baseline.
2. Зафиксируй exact terminal/tenant/SN identifiers только из входных artifacts; если соответствие неоднозначно, `BLOCKED_CONTRACT`.
3. Реализуй service-auth endpoint с `operation_id`, one-time PIN, TTL, replay/idempotency, ownership binding, audit/correlation и стабильным error model.
4. Не возвращай секреты в логи/handoff; повтор операции возвращает прежний безопасный результат по контракту и не выпускает второй PIN.
5. Добавь provider contract/security/race/replay/expired/used/CSR mismatch tests и backward compatibility terminal-facing certificate flow.
6. Выполни checks, commit/push, deploy additive endpoint на утверждённый host и smoke безопасным тестовым контекстом.

## Выход

`H-L4D-06A-PB-v1`: `API/DEPLOYMENT` с OpenAPI/schema/examples digest, identifiers, idempotency/errors/TTL без PIN values, deployed version и consumer `L4D-06B-IOT` плюс `L4D-06C-MB`.
