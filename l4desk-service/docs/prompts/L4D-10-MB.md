# L4D-10-MB — Реализовать тарифы, billing cycles и metering

```yaml
prompt_id: L4D-10-MB
scope_project: MenuBuilder
scope_root: D:\repo\platerra\Public\etranprocessing\MenuBuilder
prompt_type: billing-implementation
required_handoff_ids: [H-L4D-09-MB-v1, H-L4D-03-MB-v1, H-L4D-02-IOT-v1]
output_handoff_id: H-L4D-10-MB-v1
next_prompt_id: L4D-11-MB
branch: l4desk/l4d-10-mb
report_path: MenuBuilder/docs/l4desk/handoffs/L4D-10-MB-report.md
architecture_sections: [2, 3, 5, 6, 7, 9, 10, 13, 14, 15, 16, 17]
```

## Цель

Только в `MenuBuilder` реализуй версионированные тарифы, индивидуальные billing cycles и metering из подтверждённых IoT facts в `fin_*` ledger.

## Нормативная логика

1. Первый успешный платёж задаст anchor; месяцы — `add_months(anchor,n)` с правилом последнего существующего дня. Online не сдвигает anchor.
2. Первый по неизменяемому порядку существующий terminal бесплатен; после удаления льгота переходит следующему только вперёд.
3. Каждый другой terminal при первом аутентифицированном `device_online` в cycle получает один charge `10000` kopecks по unique `(terminal,billing_cycle)` даже при online после grace boundary.
4. Локальные сутки tenant делят active→closed intervals. Для free terminal: `billable_seconds=max(0,console+video-7200)`; для остальных free=0. Console/video не пересекаются.
5. `paid_hours=ceil(billable_seconds/3600)`, current rate `100` kopecks/hour. Округлять aggregate один раз в сутки.
6. Общая формула будущего тарифа хранит `calculated`, затем `posted=floor(calculated/100)*100`, `discarded=calculated-posted`; `calculated=posted+discarded`, discarded не переносится и не проводится.

## Работа и проверки

Реализуй immutable tariff snapshot, open/closed daily usage, late-event delta corrections, timezone/day split, source event ids/hash, idempotent posting и cycle calculation. Тестируй DST, 29–31 anchor, leap year, deletion/free transfer, duplicate/late events, midnight session, exact 120 min, 120m01s, rounding/post-reconciliation и concurrent worker. Выполни checks, commit/push, deploy в shadow mode, reconciliation smoke без реального списания.

## Выход

`H-L4D-10-MB-v1`: `API/DEPLOYMENT` с формулами, tariff/cycle/usage schemas, rounding invariants, shadow metrics, tests и consumer `L4D-11-MB`.
