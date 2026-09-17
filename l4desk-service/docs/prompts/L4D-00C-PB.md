# L4D-00C-PB — Зафиксировать baseline сертификатного контура

```yaml
prompt_id: L4D-00C-PB
scope_project: ProcessingBackend
scope_root: D:\repo\platerra\Public\etranprocessing\ProcessingBackend
prompt_type: baseline
required_handoff_ids: [H-L4D-00B-IOT-v1]
output_handoff_id: H-L4D-00C-PB-v1
next_prompt_id: L4D-00D-MEDIA
branch: l4desk/l4d-00c-pb
report_path: ProcessingBackend/docs/l4desk/handoffs/L4D-00C-PB-report.md
architecture_sections: [3, 4, 5, 7, 14, 16, 17]
```

## Цель и scope

Только в `ProcessingBackend` зафиксируй baseline PIN/CSR/X.509, terminal binding, audit и единственной Alembic-цепочки. Входной IoT handoff служит только sequence gate; IoT-код не читать.

## Задачи

1. Выполни contract gate и локальные project guidelines.
2. Инвентаризируй certificate endpoints, auth, identifiers, idempotency/replay protection, PIN TTL/one-time semantics, CSR validation, audit и error model.
3. Зафиксируй текущий Alembic head, владение миграциями, shared package version и production image/commit.
4. Запусти относящиеся тесты, `ruff`, format check и `pyright` по локальным правилам; выполни read-only provider smoke без выпуска PIN для реального терминала.
5. Runtime-код и schema в этом шаге не менять. Подготовь gap list для будущих `04B` и `06A`.
6. Commit/push только baseline report/artifacts текущего scope.

## Выход

`H-L4D-00C-PB-v1`: `REPORT`, точные endpoint/schema revision, identifier/error inventory, тесты, deployment evidence, gaps, rollback/read-only note и consumer `L4D-00D-MEDIA`.
