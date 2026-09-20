# L4D-08B-MB-FIX-01 — Устранение дефектов схемы, хешей и синхронизация handoff-контракта MenuBuilder

```yaml
prompt_id: L4D-08B-MB-FIX-01
scope_project: MenuBuilder
scope_root: D:\repo\platerra\Public\etranprocessing\MenuBuilder
prompt_type: corrective-consumer
blocked_prompt_id: L4D-08B-MB
registration_id: R-L4D-08B-MB-FIX-01-v1
required_handoff_ids:
  - H-L4D-07-IOT-v1
  - H-L4D-08A-MEDIA-v1
sequence_gate_handoff_id: H-L4D-08A-MEDIA-v1
output_handoff_id: H-L4D-08B-MB-FIX-01-v1
next_prompt_id: L4D-08B-MB
branch: l4desk/l4d-08b-mb
report_path: MenuBuilder/docs/l4desk/handoffs/L4D-08B-MB-FIX-01-report.md
candidate_format: DETACHED_V1
candidate_path: MenuBuilder/docs/l4desk/handoffs/L4D-08B-MB-FIX-01-candidate.md
architecture_sections: [1, 2, 3, 4, 5, 6, 8, 11, 12, 13, 16, 17]
```

## 1. Контекст корректирующего шага и основания отказа

Корректирующий шаг `L4D-08B-MB-FIX-01` инициирован по результатам контрольной проверки handoff-controller для шага `L4D-08B-MB` (статус первичного отчёта: `REJECTED`, контракт `H-L4D-08B-MB-v1` не принят).

Основания отклонения контроллером каскада:
1. **HASH_MISMATCH и структурный дефект схемы:** в candidate-блоке перечислено 14 путей артефактов, но указано только 12 хешей SHA-256 (пропущен `main.py`, смещены остальные хеши, отсутствует хеш для `port_3000.conf`, сам отчет не включен в артефакты).
2. **Рассинхрон коммитов и scope:** заявленный `producer_commit: 8ba8edbceae6d5a3d2b70ee6d54b97f558d5bdc0` содержит правки вне scope (`contract-handoff.md`, `port_3000.conf`) и не включает коммит с исправлением БД-ошибки `ad5a13d9fce804746f4f961812b8a026ba416bf4`.
3. **Отсутствующий файл кандидата:** ссылка на `candidate_path: MenuBuilder/docs/l4desk/handoffs/L4D-08B-MB-candidate.md` (`DETACHED_V1`) указывала на несуществующий файл (блок был ошибочно встроен в отчёт).

## 2. Цели и границы

1. Исключить артефакты вне scope `MenuBuilder` (`nginx-configs/port_3000.conf`).
2. Обеспечить строгое взаимно-однозначное соответствие количества артефактов и контрольных сумм SHA-256 (14 путей = 14 хешей).
3. Включить `MenuBuilder/backend/app/main.py` и файл отчёта в список артефактов и контрольных сумм.
4. Привязать `producer_commit` к проверенному коммиту реализации `ad5a13d9fce804746f4f961812b8a026ba416bf4` (содержащему исправление check-констрейнта `l4desk_session_active_ck` и изолированному строго рамками `MenuBuilder`).
5. Опубликовать отдельный кандидат `DETACHED_V1` по путям `candidate_path` (`L4D-08B-MB-FIX-01-candidate.md` и `L4D-08B-MB-candidate.md`).
6. Выполнить проверку тестов и линтеров `MenuBuilder`.
