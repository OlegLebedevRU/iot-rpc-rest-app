## Summary

<!-- Краткое описание изменений (1–3 предложения) -->

## Linked issue

Closes #

## Affected subprojects

- [ ] `app-service`
- [ ] `device-emulator`
- [ ] `mcp`
- [ ] `docs`
- [ ] `infra` (docker-files / nginx / rmq / compose.yaml)
- [ ] `examples`

## Breaking changes

- [ ] Yes — описать контракт изменений ниже
- [ ] No

<!-- Если Yes: что именно ломается и как мигрировать -->

## How tested

<!-- Как проверялись изменения: команды, сценарии, окружение -->

```bash
uv run pytest
uv run ruff check .
uv run black --check .
```

## PR checklist

- [ ] `uv run pytest` зелёный.
- [ ] `ruff check .` и `black --check .` без ошибок.
- [ ] Обновлены релевантные документы в `docs/` (если меняется протокол/REST/события).
- [ ] Если затронут MCP — обновлён `mcp/docs/tools-reference.md`.
- [ ] Нет секретов / реальных API‑ключей / приватных ключей в diff.
- [ ] PR ссылается на issue и кратко описывает контракт изменений.
