# L4D-01C-DOCS — Зарегистрировать принятую пару Agent/IoT контрактов

```yaml
prompt_id: L4D-01C-DOCS
scope_project: l4desk-service
scope_root: D:\repo\platerra\Public\etranprocessing\l4desk-service
prompt_type: contract-governance
required_handoff_ids: [H-L4D-01A-TOOLS-v1, H-L4D-01B-IOT-v1]
output_handoff_id: H-L4D-01C-DOCS-v1
next_prompt_id: L4D-02-IOT
branch: l4desk/l4d-01c-docs
report_path: l4desk-service/docs/handoffs/L4D-01C-DOCS-report.md
architecture_sections: [3, 4, 5, 11, 12, 16, 17, 18]
```

## Цель

Только в `l4desk-service` зарегистрируй доказанную совместимость immutable Agent contract и deployed IoT provider. Не открывай ни один runtime repository.

## Задачи

1. Проверь оба handoff, digest fixtures, version coverage, provider test/deploy/smoke evidence.
2. Сформируй accepted compatibility matrix и точные ссылки для следующих IoT-шагов.
3. При любом несовпадении topics/payload/errors/version range верни `REJECTED` и corrective prompt; не усредняй контракты.
4. Проверь Markdown/links, commit/push только docs scope.
5. Добавь собственный accepted handoff в единый журнал только после push.

## Выход

`H-L4D-01C-DOCS-v1`: `SEQUENCE_GATE/FIXTURES`, ссылки/digests принятой пары, нормативное правило backward compatibility и consumer `L4D-02-IOT`.
