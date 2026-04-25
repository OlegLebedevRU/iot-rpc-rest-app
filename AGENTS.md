# AGENTS.md — Leo4 IoT Platform

> **Источник истины для агентов:** [`.github/copilot-instructions.md`](.github/copilot-instructions.md)
> Этот файл — короткий указатель. Полный контекст, доменные правила и чек‑листы см. выше.

## TL;DR

Монорепо: FastAPI + FastStream + RabbitMQ (MQTT 5) + PostgreSQL + nginx + Docker Compose.
Python 3.14, сборка через **uv** (`uv.lock`). Ветка по умолчанию — `master`.

## Структура

| Папка | Назначение |
|---|---|
| `app-service/` | Основной сервис (FastAPI + FastStream). Тесты: `app-service/tests` |
| `device-emulator/` | Эмулятор IoT‑устройства (paho‑mqtt) |
| `mcp/` | MCP‑сервер LEO4 для AI‑ассистентов (Python ≥ 3.11) |
| `examples/` | Примеры клиентов (Python, C#, C/Win, FreeRTOS) |
| `robotics/` | Материалы по роботизированному стеку |
| `docs/` | Каноническая документация протоколов |
| `docker-files/`, `nginx/`, `rmq/` | Инфраструктура |

## Быстрый старт

```bash
uv sync                        # установить зависимости
uv run pytest                  # запустить тесты
uv run ruff check .            # линтер
uv run black --check .         # форматирование
docker compose up -d --build   # поднять инфраструктуру
```

## Ключевые документы

Перед любым изменением прочитать:

- [`docs/mqtt-rpc-protocol.md`](docs/mqtt-rpc-protocol.md) — протокол RPC через MQTT
- [`docs/1-task-workflow-doc.md`](docs/1-task-workflow-doc.md) — REST workflow задач
- [`docs/task_states.md`](docs/task_states.md) — машина состояний (READY→PENDING→LOCK→DONE/FAILED)
- [`docs/mqtt_topic_rules.md`](docs/mqtt_topic_rules.md) — правила топиков MQTT
- [`docs/correlation-data-guide.md`](docs/correlation-data-guide.md) — correlation data (обязательна)
- [`docs/method-codes-reference.md`](docs/method-codes-reference.md) — реестр method_code
- [`docs/event-protocol-mqtt.md`](docs/event-protocol-mqtt.md) — протокол событий
- [`docs/TTL.md`](docs/TTL.md) — правила декрементирования TTL
- [`docs/glossary.md`](docs/glossary.md) — глоссарий терминов

## Главные доменные ловушки

1. **`status=3 (DONE)` ≠ физическое выполнение.** Только события подтверждают факт.
2. **TTL=0 → задача EXPIRED**, не DONE.
3. **Топики MQTT** строго по шаблону: `srv/<SN>/{tsk,rsp,cmt,eva}`, `dev/<SN>/{res,evt,...}`.
4. **correlation data обязательна** для всех RPC запросов/ответов.
5. **Сертификаты** — только bind‑mount, никогда не запекать в Docker‑образ.

## Чего не делать

- Не менять `uv.lock` руками — только `uv add` / `uv lock`.
- Не коммитить `*.pem`, `*.key`, `*.pfx`, `.env`.
- Не использовать `requests` — только `httpx`.
- Не делать синхронные вызовы в async‑коде.

---

*Подробности — в [`.github/copilot-instructions.md`](.github/copilot-instructions.md) и [`CONTRIBUTING.md`](CONTRIBUTING.md).*
