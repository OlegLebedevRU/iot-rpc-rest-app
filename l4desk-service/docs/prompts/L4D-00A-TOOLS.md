# L4D-00A-TOOLS — Зафиксировать baseline Агента

```yaml
prompt_id: L4D-00A-TOOLS
scope_project: tools
scope_root: D:\repo\platerra\Public\etranprocessing\tools
prompt_type: baseline
required_handoff_ids: []
output_handoff_id: H-L4D-00A-TOOLS-v1
next_prompt_id: L4D-00B-IOT
branch: l4desk/l4d-00a-tools
report_path: tools/docs/l4desk/handoffs/L4D-00A-TOOLS-report.md
architecture_sections: [3, 4, 5, 12, 16, 17]
```

## Роль и цель

Ты — архитектор совместимости и release-инженер Агента. Выполни первый шаг каскада строго в `tools`: зафиксируй проверяемый baseline опубликованного Агента/`leo4proxy`, который следующие агенты смогут использовать без чтения исходников `tools`.

## Обязательная работа

1. Выполни bootstrap gate из `PROMPT-STANDARD.md`; убедись, что единый журнал имеет состояние `READY_FOR_00A`.
2. Прочитай локальные правила `tools`. Не открывай `MenuBuilder`, `iot-rpc-rest-app`, `ProcessingBackend`, `l4media` или `shared`.
3. Найди фактически реализованные MQTT topics, RPC lifecycle, method codes `7000/7001/7002`, обязательные/необязательные payload, timeout/cancel, certificate bootstrap, version/capabilities и release metadata.
4. Не меняй MQTT-клиент и protocol. Если для baseline требуется изменение клиента, верни `BLOCKED_SCOPE`; тип клиента нельзя выбирать самостоятельно.
5. Зафиксируй golden examples из существующего поведения, checksums опубликованного артефакта, минимально поддерживаемую версию и известные несовместимости.
6. Запусти все локальные тесты/сборку, относящиеся к Агенту и `leo4proxy`; не публикуй новый runtime artifact.
7. Создай отчёт, commit и push только документации/fixtures baseline в указанную ветку. Проверка artifact registry выполняется read-only.

## Выход и acceptance

Candidate `H-L4D-00A-TOOLS-v1` имеет `contract_kind: FIXTURES`, `deployment_status: PUBLISHED`, содержит точные artifact version/hash, topics/method codes/payload inventory, capability matrix, test evidence и адресует `L4D-00B-IOT`. Любая догадка вместо наблюдаемого контракта запрещена.
