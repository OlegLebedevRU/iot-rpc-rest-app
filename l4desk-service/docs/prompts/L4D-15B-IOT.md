# L4D-15B-IOT — Реализовать архив IoT/RPC подробностей

```yaml
prompt_id: L4D-15B-IOT
scope_project: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
prompt_type: archive-implementation
required_handoff_ids: [H-L4D-15A-DOCS-v1, H-L4D-02-IOT-v1, H-L4D-07-IOT-v1]
output_handoff_id: H-L4D-15B-IOT-v1
next_prompt_id: L4D-15C-MEDIA
branch: l4desk/l4d-15b-iot
report_path: docs/l4desk/handoffs/L4D-15B-IOT-report.md
architecture_sections: [3, 5, 6, 8, 11, 12, 14, 15, 16, 17]
```

## Цель

Только в IoT-проекте реализуй помесячную архивацию массовых device/RPC/session-event подробностей по принятому manifest contract.

## Реализация

1. Выполни gates и проверь schema/fixture digest. Не меняй общий contract.
2. Классифицируй только локально принадлежащие high-volume details; durable facts, не прочитанные обязательным consumer, и session summaries не purge.
3. Реализуй idempotent batch: select closed month older three full months → deterministic export to temp → manifest/hash → full reread/count/hash/restore sample → atomic rename → verified → bounded purge.
4. Проверяй cursor guard всех обязательных consumers и active/reopened records. Retry после crash продолжает либо безопасно пересоздаёт batch без потери/дубля.
5. Mounted path configurable; path traversal/symlink/partial disk/permission/full disk защищены; архивы не содержат секретов.
6. Тесты fixtures, deterministic hash, crash at every phase, cursor lag, restore, no-purge-on-failure и retention boundaries.
7. Checks/migrations, commit/push, deploy worker disabled, dry-run/one approved old batch smoke и rollback.

## Выход

`H-L4D-15B-IOT-v1`: `DEPLOYMENT/REPORT` с implemented manifest version, record types, cursor/purge rules, restore evidence, flags и consumer `L4D-15C-MEDIA` плюс `L4D-16-MB`.
