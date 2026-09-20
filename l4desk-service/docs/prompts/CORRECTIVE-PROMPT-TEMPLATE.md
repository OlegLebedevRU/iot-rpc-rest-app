# Шаблон corrective prompt L4Desk

Используется только после blocker/rejection основного шага. Контроллер заменяет все значения `<...>` фактическими данными и регистрирует prompt до запуска.

```text
prompt_id: <L4D-XX-SCOPE-FIX-01>
scope_project: <ровно один проект исходного шага>
scope_root: <точный локальный корень>
blocked_prompt_id: <L4D-XX-SCOPE>
required_handoff_ids:
  - <самостоятельный предметный ACCEPTED handoff>
  - <handoff с подтверждённой диагностикой, если есть>
sequence_gate_handoff_id: <последний ACCEPTED основной шаг перед заблокированным>
output_handoff_id: <H-L4D-XX-SCOPE-FIX-01-v1>
next_prompt_id: <повтор исходного шага либо следующий явно зарегистрированный prompt>
branch: l4desk/<prompt-id-lowercase>
report_path: <только внутри scope_project>/docs/l4desk/handoffs/<prompt_id>-report.md
```

Если входные handoff не адресованы corrective prompt, контроллер сначала оформляет адресную регистрацию по §8 `PROMPT-STANDARD.md`; её `registration_id` добавляется в метаданные промпта. Исходные ID не подменяются регистрацией, прежние блоки не переписываются. Для согласованного `DETACHED_V1` также указать `candidate_format: DETACHED_V1` и точный `candidate_path` внутри scope. Метаданные и пути должны совпадать с записью регистрации. Публикация пакета обязательна до запуска.

Если предметный вход содержит только чужие исходники, сначала опубликовать самостоятельный provider export по §10 стандарта. Обновлённые входные ID/commits и конечный `external_artifact_reads` задаёт контроллер в новой регистрации после отзыва прежней; исполнитель не подменяет их сам. Sequence-only ID вне required_handoff_ids не требует чтения его исходников. Для исторических CRLF-digest использовать только явно зарегистрированный `artifact_byte_binding_ids`, а не нормализовывать bytes самостоятельно.

## Обязательные инструкции агенту

1. Сначала прочитай `PROMPT-STANDARD.md` и выполни contract gate по `contract-handoff.md`.
2. Работай только в `scope_project`. Чтение за его пределами ограничено стандартными документами и конечным data-only read grant §10. Исходники/команды/изменения соседнего проекта запрещены даже для диагностики.
3. Воспроизведи ровно зафиксированный defect из входного handoff внутри текущего проекта.
4. Если defect не воспроизводится по переданным fixtures/evidence, верни `BLOCKED_CONTRACT`; не угадывай скрытую причину.
5. Добавь падающий regression test, затем минимальное исправление, не меняющее принятый контракт без отдельного provider prompt.
6. Выполни все project-local проверки, commit, push, deploy/publish и smoke по стандарту.
7. Создай локальный отчёт и candidate handoff с точной ссылкой на defect, тест, commit, deploy и replacement/supersedes. Если регистрацией утверждён `DETACHED_V1`, следуй §9 стандарта: отчёт и окончательный candidate публикуются раздельно, digest отчёта находится только в candidate, а не в самом отчёте.
8. Если исправление требует другого проекта, верни `BLOCKED_SCOPE`; контроллер создаст отдельный следующий corrective prompt для того проекта.

Corrective prompt не даёт права обходить строгую последовательность, ослаблять тесты, менять contract journal напрямую из runtime-проекта или выполнять временное несовместимое исправление.