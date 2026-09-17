# L4D-18C-IOT — Выполнить финальный production rollout IoT

```yaml
prompt_id: L4D-18C-IOT
scope_project: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
prompt_type: production-rollout
required_handoff_ids: [H-L4D-18B-PB-v1, H-L4D-17C-IOT-v1, H-L4D-01C-DOCS-v1, H-L4D-02-IOT-v1, H-L4D-06B-IOT-v1, H-L4D-07-IOT-v1, H-L4D-15B-IOT-v1]
output_handoff_id: H-L4D-18C-IOT-v1
next_prompt_id: L4D-18D-MEDIA
branch: l4desk/l4d-18c-iot
report_path: docs/l4desk/handoffs/L4D-18C-IOT-report.md
architecture_sections: [3, 4, 5, 6, 8, 11, 12, 14, 15, 16, 17, 18, 19]
```

## Цель

Только в IoT-проекте разверни принятые provider-функции и совместимость текущих Агентов. PB handoff — sequence gate; ProcessingBackend не деплоить.

## Выполнение

1. Выполни gates и exact version matrix. Не менять принятые contracts в rollout.
2. Полный local suite/build/provider fixtures, immutable image, commit/push release.
3. Выполни deploy строго по IoT runbook/утверждённому target. Если target/credentials не зафиксированы локально, `BLOCKED_DEPLOY`, не угадывать.
4. Применяй только IoT-local migrations и включай provider endpoints совместимо; destructive cleanup и archive purge остаются disabled до отдельного operational approval.
5. Smoke: current/old supported Agents, provisioning, event feed resume, one-session lock, console graceful timeout/response, video stop, archive dry-run and cursor guard.
6. Проверь queue lag, duplicate/orphan session/event counts и rollback. Не изменяй MQTT topics/method payload.

## Выход

`H-L4D-18C-IOT-v1`: `DEPLOYMENT` с production image/commit/schema/flags, Agent compatibility, smoke/metrics/rollback и consumer `L4D-18D-MEDIA` плюс `L4D-18E-MB`.
