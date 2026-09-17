# L4D-06B-IOT — Реализовать идемпотентный device provisioning contract

```yaml
prompt_id: L4D-06B-IOT
scope_project: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
prompt_type: implementation-provider
required_handoff_ids: [H-L4D-06A-PB-v1, H-L4D-02-IOT-v1]
output_handoff_id: H-L4D-06B-IOT-v1
next_prompt_id: L4D-06C-MB
branch: l4desk/l4d-06b-iot
report_path: docs/l4desk/handoffs/L4D-06B-IOT-report.md
architecture_sections: [3, 4, 5, 6, 11, 12, 14, 16, 17]
```

## Цель

Только в `iot-rpc-rest-app` реализуй versioned idempotent device provisioning и его durable facts. Certificate handoff задаёт идентификаторы/sequence, но ProcessingBackend не вызывается из этого шага без явного контракта.

## Реализация

1. Выполни gates и используй exact identifiers из `06A`/event envelope `02`; при конфликте остановись.
2. Добавь service-auth endpoint `operation_id` с состояниями requested/provisioned/failed, устойчивым device id/SN mapping и correlation.
3. Повтор идентичной операции возвращает тот же ресурс; reuse `operation_id` с другим payload — контрактная ошибка.
4. Публикуй provisioning facts через принятый durable feed. Не меняй Agent protocol и не создавай MQTT client.
5. Тесты: duplicate/concurrent request, identity conflict, tenant isolation, restart, event emission, auth/error schema и compatibility.
6. Выполни локальные checks/migrations, commit/push, deploy и provider smoke.

## Выход

`H-L4D-06B-IOT-v1`: `API/EVENT/DEPLOYMENT` с OpenAPI/event artifacts, identifiers/states/errors/idempotency, deployed version и consumer `L4D-06C-MB`.
