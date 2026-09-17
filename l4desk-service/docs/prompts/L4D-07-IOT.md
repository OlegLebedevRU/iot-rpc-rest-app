# L4D-07-IOT — Реализовать единый session lock и graceful stop

```yaml
prompt_id: L4D-07-IOT
scope_project: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
prompt_type: implementation-provider
required_handoff_ids: [H-L4D-06C-MB-v1, H-L4D-01C-DOCS-v1, H-L4D-02-IOT-v1]
output_handoff_id: H-L4D-07-IOT-v1
next_prompt_id: L4D-08A-MEDIA
branch: l4desk/l4d-07-iot
report_path: docs/l4desk/handoffs/L4D-07-IOT-report.md
architecture_sections: [3, 4, 5, 6, 8, 11, 12, 16, 17]
```

## Цель

Только в IoT-проекте реализуй окончательный технический ownership одной active console **или** video session на device и command-aware graceful stop.

## Реализация

1. Выполни gates. Не принимай финансовых решений и не открывай `MenuBuilder`.
2. Реализуй idempotent internal start/get/stop API с operation/session/correlation ids и lifecycle requested→starting→active→stopping→closed/failed.
3. Гарантируй mutual exclusion транзакцией/unique constraint: любая active/starting session блокирует другую независимо от типа; второй запрос получает стабильный conflict.
4. Video stop завершает штатный remote/media control flow. Console stop прекращает новые команды, ждёт текущий response или контрактный timeout, затем закрывает session; бесконечное ожидание запрещено.
5. Все переходы публикуй через durable feed `02`; тарифицируемый интервал только active→closed.
6. Сохрани Agent Contract v1. Не меняй MQTT client/topics/payload; новые server fields остаются внутри IoT API.
7. Тесты: simultaneous starts, duplicate operations, crashes/recovery, start failure, stale session, command response/timeout, video stop и event ordering.
8. Checks/migrations, commit/push, deploy feature-compatible provider и smoke с текущим Agent fixture.

## Выход

`H-L4D-07-IOT-v1`: `API/EVENT/DEPLOYMENT` с session schema/state/errors/timeouts, mutual exclusion evidence, Agent compatibility, deployed version и consumers `L4D-08A-MEDIA`, `L4D-08B-MB`, `L4D-12-MB`.
