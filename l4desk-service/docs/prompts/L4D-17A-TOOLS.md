# L4D-17A-TOOLS — Провести приёмку опубликованного Агента

```yaml
prompt_id: L4D-17A-TOOLS
scope_project: tools
scope_root: D:\repo\platerra\Public\etranprocessing\tools
prompt_type: acceptance
required_handoff_ids: [H-L4D-16-MB-v1, H-L4D-01A-TOOLS-v1, H-L4D-01C-DOCS-v1]
output_handoff_id: H-L4D-17A-TOOLS-v1
next_prompt_id: L4D-17B-PB
branch: l4desk/l4d-17a-tools
report_path: tools/docs/l4desk/handoffs/L4D-17A-TOOLS-report.md
architecture_sections: [3, 4, 5, 11, 12, 16, 17]
```

## Цель

Только в `tools` проведи финальную локальную приёмку текущего опубликованного Agent artifact против принятого Agent Contract v1. Не меняй IoT/provider или production Agent installations.

## Проверки

1. Выполни все gates; `16` — обязательный sequence gate.
2. Получи именно версию/sha256 опубликованного artifact из handoff. Не подменяй новой локальной сборкой.
3. Запусти golden fixtures и regression suites для certificate bootstrap, presence, RPC lifecycle, method codes `7000/7001/7002`, console command/result/cancel/timeout и stream control.
4. Проверь declared version/capabilities и backward compatibility минимально поддерживаемой версии.
5. Не создавай/не меняй MQTT client. Обнаруженный defect фиксируй тестом и возвращай corrective prompt; несовместимый protocol не публиковать.
6. Зафиксируй reproducible commands/results, artifact registry URL/version/hash. Commit/push acceptance report; deploy отсутствует, publish означает доступный отчёт и неизменный artifact evidence.

## Выход

`H-L4D-17A-TOOLS-v1`: `REPORT/FIXTURES`, verdict only `ACCEPTED` при всех зелёных checks, exact Agent artifact/version/hash, compatibility matrix и consumer `L4D-17B-PB`.
