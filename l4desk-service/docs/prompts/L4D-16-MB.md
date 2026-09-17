# L4D-16-MB — Реализовать финансовые archive manifests и retention

```yaml
prompt_id: L4D-16-MB
scope_project: MenuBuilder
scope_root: D:\repo\platerra\Public\etranprocessing\MenuBuilder
prompt_type: archive-coordination
required_handoff_ids: [H-L4D-15A-DOCS-v1, H-L4D-15B-IOT-v1, H-L4D-15C-MEDIA-v1, H-L4D-14-MB-v1]
output_handoff_id: H-L4D-16-MB-v1
next_prompt_id: L4D-17A-TOOLS
branch: l4desk/l4d-16-mb
report_path: MenuBuilder/docs/l4desk/handoffs/L4D-16-MB-report.md
architecture_sections: [3, 5, 6, 7, 9, 10, 14, 15, 16, 17]
```

## Цель

Только в `MenuBuilder` связать внешние verified archive manifests с source hashes/Хабом и реализовать retention controls. Не запускай purge в IoT/l4media и не открывай их volumes/DB напрямую сверх contract artifact/API.

## Реализация

1. Выполни все gates, сверь единую manifest version и project-owner outputs.
2. Импортируй manifest идемпотентно по `archive_batch_id+owner`, validate schema/hash metadata/status и связывай с локальными source event ids/hashes без FK в удаляемые детали.
3. Финансовые ledger/payments/cycles/balance и daily/monthly aggregates никогда не удаляются этим worker; session summary остаётся online.
4. Показывай Hub archive state/prepared/verified/purged/failed, checksum/count mismatch и location reference с RBAC, но не раскрывай filesystem path обычному user.
5. Контролируй минимум 3 года financial/technical archive retention, mounted volume availability и backup evidence; никакого silent purge при unavailable storage.
6. Тесты invalid/duplicate manifest, owner mismatch, source hash mismatch, archived drill-down, retention boundary и no-financial-delete.
7. Checks/build, commit/push, deploy consumer/UX restricted, smoke against published manifest fixtures.

## Выход

`H-L4D-16-MB-v1`: `API/DEPLOYMENT` с manifest import/link/retention/Hub contract, invariants/tests/deployed version и consumer `L4D-17A-TOOLS`.
