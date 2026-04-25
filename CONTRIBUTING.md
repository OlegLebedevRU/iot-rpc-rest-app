# Contributing to Leo4 IoT Platform

Спасибо за интерес к проекту! Этот документ описывает процесс разработки и правила для контрибьюторов (людей и агентов).

## Требования к окружению

- Python 3.14
- [uv](https://docs.astral.sh/uv/) — менеджер зависимостей
- Docker & Docker Compose
- Git

## Поднятие окружения

```bash
# 1. Клонировать репозиторий
git clone https://github.com/OlegLebedevRU/iot-rpc-rest-app.git
cd iot-rpc-rest-app

# 2. Установить зависимости через uv
uv sync

# 3. Поднять инфраструктуру (RabbitMQ, PostgreSQL, nginx)
docker compose up -d --build

# 4. Проверить логи сервиса
docker compose logs -f app-service
```

> **Важно:** никогда не используйте `pip install` напрямую для основного монорепо. Только `uv sync` / `uv add`.

Подпроект `mcp/` управляется отдельно:

```bash
cd mcp
pip install -e ".[dev]"
pytest -v
```

## Запуск тестов

```bash
# Все тесты
uv run pytest

# Только async‑тесты
uv run pytest -m anyio

# Тесты конкретного подпроекта
uv run pytest app-service/tests/
```

## Линтинг и форматирование

```bash
uv run ruff check .        # линтер
uv run ruff check . --fix  # авто‑исправление
uv run black .             # форматирование
uv run black --check .     # проверка без изменений
```

Все PR должны проходить `ruff check .` и `black --check .` без ошибок.

## Конвенция веток

Все ветки создаются от `master`:

| Префикс | Назначение |
|---|---|
| `feat/` | Новая функциональность |
| `fix/` | Исправление ошибок |
| `docs/` | Только документация |
| `chore/` | Рутинные задачи, зависимости, конфиги |
| `refactor/` | Рефакторинг без изменения поведения |
| `test/` | Добавление или исправление тестов |

Примеры: `feat/mqtt-topic-filter`, `fix/task-ttl-decrement`, `docs/glossary`.

## Conventional Commits

Формат сообщения коммита:

```
<type>(<scope>): <description>

[optional body]

[optional footer: refs #issue]
```

Типы: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `perf`, `ci`.

Примеры:
```
feat(app-service): add correlation data validation for MQTT RPC
fix(device-emulator): correct mTLS certificate path on Windows
docs(mqtt): update method-codes-reference with new codes
chore: update uv.lock dependencies
```

## Процесс Pull Request

1. **Маленькие PR** — один PR решает одну задачу.
2. Ветка создаётся от актуального `master`.
3. PR **обязательно** ссылается на issue (`refs #N` или `closes #N`).
4. Заполните шаблон PR полностью.
5. Дождитесь зелёного CI и ревью от `@OlegLebedevRU`.

### Чек‑лист перед открытием PR

- [ ] `uv run pytest` зелёный.
- [ ] `ruff check .` и `black --check .` без ошибок.
- [ ] Обновлены релевантные документы в `docs/` (если меняется протокол/REST/события).
- [ ] Если затронут MCP — обновлён `mcp/docs/tools-reference.md`.
- [ ] Нет секретов / реальных API‑ключей / приватных ключей в diff.
- [ ] PR ссылается на issue и кратко описывает контракт изменений.

## Агентские PR

PR, открытые AI‑агентами (GitHub Copilot coding agent, Codex, Claude Code, Cursor и т.п.), должны:

- Следовать всем правилам из [`.github/copilot-instructions.md`](.github/copilot-instructions.md).
- Использовать тот же чек‑лист и шаблон PR, что и человеческие PR.
- Не изменять `uv.lock` вручную — только через `uv add` / `uv lock`.
- Не коммитить сертификаты, приватные ключи или `.env`‑файлы.

## Доменные правила

Перед изменениями в `app-service/` или протоколах обязательно прочитайте:

- [`docs/mqtt-rpc-protocol.md`](docs/mqtt-rpc-protocol.md)
- [`docs/task_states.md`](docs/task_states.md)
- [`docs/mqtt_topic_rules.md`](docs/mqtt_topic_rules.md)
- [`docs/correlation-data-guide.md`](docs/correlation-data-guide.md)

Подробнее — в [`AGENTS.md`](AGENTS.md) и [`.github/copilot-instructions.md`](.github/copilot-instructions.md).

## Файлы-исключения

Архивные/служебные документы-исключения (например, migration/refactor) не должны лежать в корне репозитория. Размещайте их только в папке [`docs/exceptions/`](docs/exceptions/).
