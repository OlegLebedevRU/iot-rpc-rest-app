# AGENTS.md — Leo4 IoT Platform

> **Источник истины для агентов:** [`.github/copilot-instructions.md`](.github/copilot-instructions.md)
> Этот файл — короткий указатель. Полный контекст, доменные правила и чек‑листы см. выше.

## TL;DR

Монорепо: FastAPI + FastStream + RabbitMQ (MQTT 5) + PostgreSQL + Docker Compose.
Python 3.14, сборка через **uv** (`uv.lock`). Ветка по умолчанию — `master`.

## Структура и контекст агента

### Обязательный контекст

| Папка / Файл | Назначение |
|---|---|
| `app-service/` | Основной сервис (FastAPI + FastStream). Тесты: `app-service/tests` |
| `docs/` | Каноническая документация протоколов и интеграций |
| `docs/exceptions/` | Служебные/исторические документы-исключения |
| `docker-files/`, `rmq/` | Инфраструктура сервиса приложения и RabbitMQ |

### Исключено из обязательного контекста агентов
Следующие каталоги **не входят в обязательный контекст агентов** и не должны исследоваться без явного запроса:
- `device-emulator/` — эмулятор IoT‑устройства (paho‑mqtt). См. `device-emulator/README.md`
- `mcp/` — MCP‑сервер LEO4 для AI‑ассистентов (Python ≥ 3.11)
- `examples/` — примеры клиентов (Python, C#, C/Win, FreeRTOS)
- `robotics/` — материалы по роботизированному стеку

### Nginx и инфраструктура Compose
- Все конфиги и сами контейнеры Nginx **не управляются данным проектом**, любые конфиги Nginx в репозитории (`nginx/`, `nginx-configs/`) считаются **неавторитетными**.
- `nginx/` и `nginx-configs/` в данном проекте **исключаются из инфраструктуры для compose**.
- **Прямое изменение конфигов Nginx на сервере запрещено:** при любом решении проблем и отладке прямое изменение не допускается — необходимо уведомить владельца и получить ручную инструкцию о порядке действий.

## Быстрый старт

```bash
uv sync                              # установить зависимости
uv run pytest                        # запустить тесты
uv run ruff check .                  # линтер
uv run black --check .               # форматирование
docker compose up -d --build app1    # собрать и поднять только app1 (или docker compose up -d --no-deps app1)
```

## Ключевые документы

Перед любым изменением прочитать:

- [`docs/mqtt-rpc-protocol.md`](docs/mqtt-rpc-protocol.md) — протокол RPC через MQTT
- [`docs/1-task-workflow-doc.md`](docs/1-task-workflow-doc.md) — REST workflow задач
- [`docs/task_states.md`](docs/task_states.md) — машина состояний (READY→PENDING→LOCK→DONE/FAILED)
- [`docs/mqtt_topic_rules.md`](docs/mqtt_topic_rules.md) — актуальные правила топиков MQTT
- [`docs/correlation-data-guide.md`](docs/correlation-data-guide.md) — correlation data (обязательна)
- [`docs/method-codes-reference.md`](docs/method-codes-reference.md) — реестр method_code (реестр по факту не полный, динамически расширяется и может отставать; не блокирует разработку, но мутации новых/старых кодов желательно уточнять)
- [`docs/event-protocol-mqtt.md`](docs/event-protocol-mqtt.md) — протокол событий
- [`docs/TTL.md`](docs/TTL.md) — правила декрементирования TTL
- [`docs/glossary.md`](docs/glossary.md) — глоссарий терминов
- [`docs/manual-app1-deploy-runbook.md`](docs/manual-app1-deploy-runbook.md) — ручной деплой только `app1` (сборка на хосте / GHCR по запросу), backup/rollback и проверки

## Деплой `app1` и защита инфраструктуры

Основной и фактический сценарий деплоя `app1` — сборка напрямую на целевом хосте
через `docker compose build app1` с последующим перезапуском
`docker compose up -d --no-deps app1`. Деплой готовых образов из GHCR
(`docker compose pull app1`) используется **только при наличии прямого указания**.
Если пользователь просит «только app», следовать
[`docs/manual-app1-deploy-runbook.md`](docs/manual-app1-deploy-runbook.md):
делать backup `.env`, выполнять `docker compose up -d --no-deps app1`, не трогая
остальные сервисы.

**Критическое правило: НИКОГДА не пересоздавать `pg`, `rabbitmq`, `nginx`, `nginx-mutual`, `pgadmin`, `certbot` без прямого указания.**

## Главные доменные ловушки

1. **`status=3 (DONE)` ≠ физическое выполнение.** Только события подтверждают факт.
2. **TTL=0 → задача EXPIRED**, не DONE.
3. **Топики MQTT** по актуальному состоянию расширены:
   - Server → Device: `srv/<SN>/{tsk,rsp,cmt,eva,ctl}`
   - Device → Server: `dev/<SN>/{req,ack,res,evt,out,ctl}` (а также зарезервированные `app`, `svc`)
4. **Реестр method_code** по факту не полный, динамически расширяется и может отставать: это не должно блокировать, но желательно уточнять при наличии мутаций новых или старых кодов.
5. **correlation data обязательна** для всех RPC запросов/ответов.
6. **Сертификаты** — только bind‑mount, никогда не запекать в Docker‑образ.

## Чего не делать

- **Никогда не пересоздавать `pg`, `rabbitmq`, `nginx`, `nginx-mutual`, `pgadmin`, `certbot` без прямого указания.**
- **Не изменять конфиги Nginx напрямую на сервере** при отладке и устранении проблем (уведомить владельца и получить инструкцию).
- **Не считать конфиги `nginx/` и `nginx-configs/` авторитетными** (они исключены из инфраструктуры compose данного проекта).
- **Не блокироваться из-за отсутствия кодов в реестре method_code** (реестр динамический; уточнять мутации).
- Не инспектировать `device-emulator/`, `mcp/`, `examples/`, `robotics/` без прямого запроса.
- Не менять `uv.lock` руками — только `uv add` / `uv lock`.
- Не коммитить `*.pem`, `*.key`, `*.pfx`, `.env`.
- Не использовать `requests` — только `httpx`.
- Не делать синхронные вызовы в async‑коде.

---

*Подробности — в [`.github/copilot-instructions.md`](.github/copilot-instructions.md) и [`CONTRIBUTING.md`](CONTRIBUTING.md).*
