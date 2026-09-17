# Шаблон corrective prompt L4Desk

Используется только после blocker/rejection основного шага. Контроллер заменяет все значения `<...>` фактическими данными и регистрирует prompt до запуска.

```text
prompt_id: <L4D-XX-SCOPE-FIX-01>
scope_project: <ровно один проект исходного шага>
scope_root: <точный локальный корень>
blocked_prompt_id: <L4D-XX-SCOPE>
required_handoff_ids:
  - <последний ACCEPTED handoff перед заблокированным шагом>
  - <handoff с подтверждённой диагностикой, если есть>
output_handoff_id: <H-L4D-XX-SCOPE-FIX-01-v1>
next_prompt_id: <повтор исходного шага либо следующий явно зарегистрированный prompt>
branch: l4desk/<prompt-id-lowercase>
report_path: <только внутри scope_project>/docs/l4desk/handoffs/<prompt_id>-report.md
```

## Обязательные инструкции агенту

1. Сначала прочитай `PROMPT-STANDARD.md` и выполни contract gate по `contract-handoff.md`.
2. Работай только в `scope_project`. Не открывай и не изменяй соседний проект даже для диагностики.
3. Воспроизведи ровно зафиксированный defect из входного handoff внутри текущего проекта.
4. Если defect не воспроизводится по переданным fixtures/evidence, верни `BLOCKED_CONTRACT`; не угадывай скрытую причину.
5. Добавь падающий regression test, затем минимальное исправление, не меняющее принятый контракт без отдельного provider prompt.
6. Выполни все project-local проверки, commit, push, deploy/publish и smoke по стандарту.
7. Создай локальный отчёт и candidate handoff с точной ссылкой на defect, тест, commit, deploy и replacement/supersedes.
8. Если исправление требует другого проекта, верни `BLOCKED_SCOPE`; контроллер создаст отдельный следующий corrective prompt для того проекта.

Corrective prompt не даёт права обходить строгую последовательность, ослаблять тесты, менять contract journal напрямую из runtime-проекта или выполнять временное несовместимое исправление.