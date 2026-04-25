# Leo4 IoT Platform — agent onboarding

## TL;DR
Транспортный фреймворк для IoT: REST API + RPC через MQTT 5 (RabbitMQ) + PKI/mTLS.
Стек: Python 3.14, FastAPI, FastStream, SQLAlchemy/asyncpg, Alembic, RabbitMQ (MQTT 5), nginx, Docker Compose.
Сборка зависимостей — **uv** (`uv.lock`), не pip/poetry. Ветка по умолчанию — `master`.

## Структура монорепо
- `app-service/`        — основной сервис (FastAPI + FastStream). Тесты: `app-service/tests`.
- `device-emulator/`    — эмулятор IoT‑устройства (paho‑mqtt). См. `device-emulator/README.md`.
- `mcp/`                — MCP‑сервер LEO4 для AI‑ассистентов. Своё `pyproject.toml`, Python ≥ 3.11.
- `examples/`           — примеры клиентов (Python, C#, C/Win, FreeRTOS).
- `robotics/`           — материалы по роботизированному стеку.
- `docker-files/`, `nginx/`, `nginx-configs/`, `rmq/` — инфраструктура для compose.
- `docs/`               — каноническая документация протоколов и интеграций.
- `docs/exceptions/`    — служебные/исторические документы-исключения (не хранить в корне репозитория).

## Обязательно к прочтению перед изменениями
1. `docs/mqtt-rpc-protocol.md` — топики, correlation data, polling/trigger.
2. `docs/1-task-workflow-doc.md` — REST workflow задач (touch_task, статусы).
3. `docs/task_states.md` — машина состояний задачи (READY→PENDING→LOCK→DONE/FAILED).
4. `docs/event-protocol-mqtt.md` + `docs/2-events-api-format-description.md` — события.
5. `docs/method-codes-reference.md` — реестр method_code.
6. `docs/event-property-tags.md` — числовые теги payload.
7. `docs/3-webhooks.md` — push‑уведомления.
8. `docs/correlation-data-guide.md` — обязательная correlation data в RPC.
9. `docs/mqtt_topic_rules.md` — правила топиков.

## Команды разработки
```bash
# окружение
uv sync                                  # ставит зависимости из uv.lock
uv run pytest                            # тесты (testpaths = app-service/tests)
uv run pytest -m anyio                   # async‑тесты
uv run ruff check . && uv run black .    # линт/формат

# инфраструктура
docker compose up -d --build             # поднять всё (rmq, nginx, app-service, ...)
docker compose logs -f app-service
```

Подпроект `mcp/` живёт своей жизнью:
```bash
cd mcp && pip install -e ".[dev]" && pytest -v
LEO4_DRY_RUN=1 python -m leo4_mcp        # без реальной сети
```

## Конвенции кода
- Python 3.14, type hints обязательны, `from __future__ import annotations` где уместно.
- Async‑first: FastAPI + FastStream, `asyncpg`, `aio-pika`. Никакого блокирующего IO в хэндлерах.
- Pydantic v2 (`pydantic-core>=2.41`, `pydantic-settings`).
- Миграции — только Alembic (`alembic revision --autogenerate`).
- Логи — `logging` (см. `LOG_LEVEL` env), без `print`.
- Секреты — только через env / `.env` (см. `.gitignore`), никогда в коде или тестах.
- Сертификаты (mTLS) — bind‑mount, не запекать в образ (см. `device-emulator/README.md`).

## Доменные правила, которые часто ломают
- **`status=3 (DONE)` ≠ физическое выполнение.** Подтверждение — только через события (`event_type_code` 13/14 и т.п.). См. `mcp/README.md` → "DONE ≠ Physically Executed".
- TTL декрементируется по правилам из `docs/TTL.md`; при TTL=0 задача EXPIRED.
- Топики MQTT строго по `docs/mqtt_topic_rules.md`: `srv/<SN>/{tsk,rsp,cmt,eva}`, `dev/<SN>/{res,evt,...}`, где `<SN>` = CN сертификата.
- correlation data — обязательна для сопоставления req/resp.

## Pull request чек‑лист для агента
- [ ] `uv run pytest` зелёный.
- [ ] `ruff check .` и `black --check .` без ошибок.
- [ ] Обновлены релевантные документы в `docs/` (если меняется протокол/REST/события).
- [ ] Если затронут MCP — обновлён `mcp/docs/tools-reference.md`.
- [ ] Нет секретов / реальных API‑ключей / приватных ключей в diff.
- [ ] PR ссылается на issue и кратко описывает контракт изменений.

## Чего НЕ делать
- Не менять `uv.lock` руками — только через `uv add` / `uv lock`.
- Не коммитить `*.pem`, `*.key`, `*.pfx`, `.env`.
- Не переименовывать топики MQTT и method_code без обновления `docs/method-codes-reference.md`.
- Не делать sync‑вызовы в async‑коде; не использовать `requests` (есть `httpx`).
- Не ломать обратную совместимость REST без бампа версии и записи в `docs/`.
