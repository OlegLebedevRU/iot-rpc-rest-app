# L4D-17F-DOCS — Провести black-box E2E и оформить решение о приёмке

```yaml
prompt_id: L4D-17F-DOCS
scope_project: l4desk-service
scope_root: D:\repo\platerra\Public\etranprocessing\l4desk-service
prompt_type: black-box-acceptance
required_handoff_ids: [H-L4D-17A-TOOLS-v1, H-L4D-17B-PB-v1, H-L4D-17C-IOT-v1, H-L4D-17D-MEDIA-v1, H-L4D-17E-MB-v1]
output_handoff_id: H-L4D-17F-DOCS-v1
next_prompt_id: L4D-18A-SHARED
branch: l4desk/l4d-17f-docs
report_path: l4desk-service/docs/handoffs/L4D-17F-DOCS-report.md
architecture_sections: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 13, 14, 15, 16, 17, 18, 19]
```

## Цель

Только в `l4desk-service` принять или отклонить MVP по black-box deployed interfaces и пяти принятым acceptance reports. Runtime repositories и DB не открывать; runtime не менять.

## Приёмка

1. Выполни gates, проверь все commit/image/schema/contract/artifact digests и отсутствие скрытых waiver.
2. По разрешённым test/public/internal interfaces выполни end-to-end: self-registration→email→tenant→terminal→provisioning/PIN→current Agent online→одна console/video→session facts→usage→payment→ledger/balance→grace/block/stop→Hub→archive manifest/restore evidence.
3. Отдельно black-box проверь старого user и текущий Agent, duplicate/retry paths, correlation id end-to-end и отсутствие одновременных console/video.
4. Не выдумывай недоступное evidence. Невозможность проверить обязательный критерий означает `BLOCKED_CONTRACT/DEPLOY`, не условное acceptance.
5. Все тестовые платежи/email/terminals должны иметь заранее утверждённый безопасный режим и cleanup lifecycle.
6. При defect выпусти список отдельных corrective prompt ids с одним scope каждый; `H-L4D-17F-DOCS-v1` не добавляй.
7. При полном успехе создай acceptance report, commit/push и добавь accepted handoff в единый журнал.

## Выход

`H-L4D-17F-DOCS-v1`: `REPORT/SEQUENCE_GATE` с E2E evidence, accepted version matrix, zero critical defects и consumer `L4D-18A-SHARED`.
