# L4D-01A-TOOLS — Опубликовать Agent Compatibility Contract v1

```yaml
prompt_id: L4D-01A-TOOLS
scope_project: tools
scope_root: D:\repo\platerra\Public\etranprocessing\tools
prompt_type: contract-provider
required_handoff_ids: [H-L4D-00G-DOCS-v1]
output_handoff_id: H-L4D-01A-TOOLS-v1
next_prompt_id: L4D-01B-IOT
branch: l4desk/l4d-01a-tools
report_path: tools/docs/l4desk/handoffs/L4D-01A-TOOLS-report.md
architecture_sections: [3, 4, 5, 11, 12, 16, 17]
```

## Цель

Только в `tools` преврати наблюдаемый Agent baseline в immutable `Agent Compatibility Contract v1` и executable golden vectors. Не меняй поведение опубликованного Агента.

## Реализация

1. Выполни contract gate. Используй только сведения, вошедшие в принятый central baseline, и локальный код `tools`.
2. Зафиксируй topic patterns, QoS/retain, payload schemas, method codes, RPC lifecycle, ack/result/error/timeout/cancel, certificate identity, version/capabilities.
3. Добавь golden fixtures и backward-compatibility tests, воспроизводящие текущий опубликованный release.
4. Не создавай/не меняй MQTT-клиент. Если это необходимо, остановись: отсутствует обязательное уточнение `main_app|extra_service`.
5. Версионируй contract additively; запрещены переименование topics/codes и изменение обязательных типов.
6. Выполни все локальные проверки, commit/push и публикацию contract/fixtures как immutable artifacts; новый Agent binary не выпускать.

## Выход

`H-L4D-01A-TOOLS-v1`: `FIXTURES`, exact contract version, files/digests, published Agent versions covered, compatibility/error semantics и consumer `L4D-01B-IOT`.
