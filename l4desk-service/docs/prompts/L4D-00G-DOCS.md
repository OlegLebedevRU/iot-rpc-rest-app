# L4D-00G-DOCS — Собрать принятый baseline и карту контрактов

```yaml
prompt_id: L4D-00G-DOCS
scope_project: l4desk-service
scope_root: D:\repo\platerra\Public\etranprocessing\l4desk-service
prompt_type: documentation-governance
required_handoff_ids: [H-L4D-00A-TOOLS-v1, H-L4D-00B-IOT-v1, H-L4D-00C-PB-v1, H-L4D-00D-MEDIA-v1, H-L4D-00E-MB-v1, H-L4D-00F-SHARED-v1]
output_handoff_id: H-L4D-00G-DOCS-v1
next_prompt_id: L4D-01A-TOOLS
branch: l4desk/l4d-00g-docs
report_path: l4desk-service/docs/handoffs/L4D-00G-DOCS-report.md
architecture_sections: [1, 3, 4, 5, 11, 12, 17, 18, 19]
```

## Цель

Только в `l4desk-service` собери шесть фактически принятых baseline handoff в центральную version/contract matrix. Не открывай исходники runtime-проектов и не «исправляй» их отчёты.

## Задачи

1. Выполни contract gate для всех шести id и проверь artifacts/digests.
2. Сопоставь identifiers, версии, ownership и обнаруженные gaps. Различия не согласовывай молча: конфликт означает `BLOCKED_CONTRACT`.
3. Создай central baseline report, карту provider/consumer contracts и перечень решений, которые должен фактически зафиксировать этап `01`.
4. Не переносить непроверенные утверждения из архитектуры в статус implemented.
5. Проверь Markdown/links, commit/push только `l4desk-service`.
6. После успешной проверки сам добавь `H-L4D-00G-DOCS-v1` в единый журнал.

## Выход

`REPORT/SEQUENCE_GATE` с digest central matrix, точными принятыми baseline versions, unresolved gaps без `TBD` в нормативной части и consumer `L4D-01A-TOOLS`.
