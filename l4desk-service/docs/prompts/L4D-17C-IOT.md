# L4D-17C-IOT — Провести приёмку device/RPC-контура

```yaml
prompt_id: L4D-17C-IOT
scope_project: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
prompt_type: acceptance
required_handoff_ids: [H-L4D-17B-PB-v1, H-L4D-01C-DOCS-v1, H-L4D-02-IOT-v1, H-L4D-06B-IOT-v1, H-L4D-07-IOT-v1, H-L4D-15B-IOT-v1]
output_handoff_id: H-L4D-17C-IOT-v1
next_prompt_id: L4D-17D-MEDIA
branch: l4desk/l4d-17c-iot
report_path: docs/l4desk/handoffs/L4D-17C-IOT-report.md
architecture_sections: [3, 4, 5, 6, 8, 11, 12, 14, 15, 16, 17]
```

## Цель

Только в `iot-rpc-rest-app` провести integrated project-local acceptance device registry/provisioning, Agent adapter, event feed, session lock/graceful stop и archive worker.

## Проверки

1. Выполни все gates и сверь deployed versions/contracts/digests.
2. Запусти полный local suite и provider fixtures: current Agent compatibility, provisioning idempotency, durable cursor/replay, simultaneous console/video rejection, lifecycle events, console response/timeout stop, video stop.
3. Проверь archive dry-run/verified restore/cursor guard/no-purge failure path. Не удаляй production details в acceptance.
4. Выполни production-safe smoke только через IoT interfaces с test device/fixtures; соседние сервисы не диагностируй из их репозиториев.
5. Измерь event lag/start-stop latency и orphan/duplicate counts. Любая ошибка — corrective prompt, а не изменение в acceptance-шаге.
6. Commit/push acceptance report с exact image/commit/config flags/rollback.

## Выход

`H-L4D-17C-IOT-v1`: `REPORT/DEPLOYMENT` с complete IoT verdict/evidence, contract versions, metrics, archive restore и consumer `L4D-17D-MEDIA`.
