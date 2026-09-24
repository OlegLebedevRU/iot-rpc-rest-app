# H-L4D-REDIS-IOT-01-v1 — Отчёт о внедрении постоянного хранения оперативных сессий и Presence в Redis (`iot-rpc-rest-app`)

```yaml
handoff_id: H-L4D-REDIS-IOT-01-v1
registration_id: R-L4D-REDIS-IOT-01-v1
prompt_id: L4D-REDIS-IOT-01
prompt_type: implementation-provider
scope_project: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
git_branch: l4desk/l4d-redis-iot-01
producer_commit: 1745074e5ad5a4bfae6741743f05db5ef32095f9
contract_version: 1.0.0
schema_revision: 2026-09-24-v1
candidate_format: DETACHED_V1
authorized_inputs:
  - handoff_id: H-L4D-07-IOT-v1
    contract_version: 1.0.0
    producer_commit: c4e892f4c1dbf8f967109e8a06c3f63b0c9bd483
  - handoff_id: H-L4D-02-IOT-v1
    contract_version: 1.0.0
    producer_commit: a5524d356dda343eca96010d16535d9f37ff4ece
sequence_gate_handoff_id: H-L4D-07-IOT-v1
output_handoff_id: H-L4D-REDIS-IOT-01-v1
next_prompt_id: L4D-08A-MEDIA
architecture_sections: [3, 4, 5, 6, 8, 11, 12, 16, 17]
status: READY
```

---

## 1. Executive Summary

В рамках задачи `L4D-REDIS-IOT-01` оперативное состояние удалённого ввода (`LeaseRegistry`), оперативное присутствие терминалов (`PresenceRegistry`) и активные сессии потокового вывода консоли (`DiagnosticsSessionRegistry`) успешно переведены из in-memory структур процесса в распределённое хранилище **Redis (DB 0)**.

### Ключевые результаты реализации:
1. **Клиентский слой Redis (`app-service/core/redis_helper.py`, `core/config.py`)**:
   - Настройка `RedisConfig` добавлена в класс `Settings` с автоматическим распознаванием запуска внутри Docker-контейнера (`auto_rewrite_docker`) и маршрутизацией на сервис `redis:6379`.
   - Управление пулом соединений (`ConnectionPool`) и клиентом `Redis` инкапсулировано в синглтоне `redis_helper`.
   - Инициализация (`init_pool`) и корректное закрытие (`close_pool`) встроены в `lifespan` FastAPI-приложения (`create_api_app.py`).
   - Функция проверки здоровья `ping()` с логированием и отказоустойчивой обработкой `ConnectionError` / `TimeoutError`.
   - В `compose.yaml` сервис `app1` дополнен зависимостью `depends_on: redis (service_healthy)`.

2. **Реализация `RedisLeaseRegistry` (`app-service/core/remote_input/leases.py`)**:
   - Сохранение лизов в Redis Hash `l4d:lease:<lease_id>` со скользящим TTL `ttl_sec + 30s`.
   - Указатель активного лиза устройства `l4d:lease:active:<sn>` со строгим TTL `ttl_sec`.
   - Атомарные транзакции на базе Redis Pipeline (`WATCH` / `MULTI` / `EXEC`) для захвата, продления (`touch`), обновления области действия (`upgrade_scope`) и отзыва (`revoke`).
   - Идемпотентный повторный захват и повышение прав для одного и того же владельца и сессии.
   - Защита от конфликтов (`LeaseConflictError`) при попытке перехвата другим пользователем или сессией.
   - Проверка владельца (`owner_user_id`) при попытке освобождения лиза.
   - Публикация событий в Redis Pub/Sub канал `l4d:pubsub:lease_revoked` с трансляцией досрочного отзыва во все локальные очереди слушателей.
   - Строгая обработка `ConnectionError`: при отказе Redis ошибка не подавляется, дублирующие лизы не создаются.

3. **Реализация `RedisPresenceRegistry` (`app-service/core/remote_input/presence.py`)**:
   - Состояние агента `l4d:presence:<sn>` хранится в Redis Hash с TTL 90 с (`presence_stale_sec`).
   - Снимок инвентаря мониторов `l4d:inventory:<sn>` хранится в виде JSON со сроком жизни 24 часа (86400 с).
   - Параметры стрима `l4d:stream:<sn>` сохраняются с динамическим TTL (90 с для состояния `running`, 300 с для завершённых/ошибочных).
   - Защита от гонок LWT: устаревшие offline-сообщения отбрасываются, если в Redis зафиксировано более позднее online-состояние.
   - Мгновенное восстановление инвентаря и онлайн-статуса при холодном перезапуске `app1`.

4. **Персистентность сессий диагностики `RedisDiagnosticsSessionRegistry` (`app-service/core/diagnostics/sessions.py`)**:
   - Метаданные сессий консольного вывода (`dev/<SN>/out`) сохраняются в Redis Hash `l4d:diag:session:<session_id>` с TTL `ttl_sec`.
   - Возможность восстановления дескрипторов сессий между воркерами и после перезапуска.
   - Синхронное удаление и очистка сессий по истечении таймаута.

5. **100% сохранение обратной совместимости внешних контрактов**:
   - Сигнатуры REST API (`/api/internal/v1/*`, `/api/v1/*`) не изменились.
   - Топики MQTT (`srv/<SN>/*`, `dev/<SN>/*`), коды методов (7000, 7001, 7002), формат payloads и протокол `L4RTP/1` сохранены без изменений.
   - Таблицы `tb_remote_sessions` и `tb_remote_session_events` в PostgreSQL остаются единственным постоянным источником финансового и технического аудита.

---

## 2. Input Contract Gates Verification

| Required Handoff ID | Статус в журнале | Scope / Producer | Типы контрактов | Соответствие требованиям |
|---|---|---|---|---|
| `H-L4D-07-IOT-v1` | `ACCEPTED` | `iot-rpc-rest-app` | `API`, `EVENT`, `DEPLOYMENT` | Входной sequence gate проверен: unified session lock и command-aware graceful stop согласованы. SHA-256 артефактов совпадает. |
| `H-L4D-02-IOT-v1` | `ACCEPTED` | `iot-rpc-rest-app` | `API`, `EVENT`, `DEPLOYMENT` | Контракт durable event feed `02` и схема аудита сессий соблюдены без изменений. SHA-256 артефактов совпадает. |

---

## 3. Перечень изменённых и созданных файлов

| Файл | Статус | Описание изменений |
|---|---|---|
| `pyproject.toml` | Изменён | Добавлена зависимость `redis>=5.0.0`. |
| `uv.lock` | Изменён | Зафиксирована версия `redis==8.1.0`. |
| `compose.yaml` | Изменён | Добавлена зависимость сервиса `app1` от `redis: {condition: service_healthy}`. |
| `app-service/core/config.py` | Изменён | Добавлена модель `RedisConfig` с Docker-rewrite логикой и поле `redis` в `Settings`. |
| `app-service/core/redis_helper.py` | Создан | Модуль пула соединений, `RedisHelper`, `init_pool`, `close_pool`, `ping`. |
| `app-service/core/remote_input/leases.py` | Изменён | Реализован адаптер `RedisLeaseRegistry` с атомарными транзакциями, Pub/Sub каналом и сохранением совместимости. |
| `app-service/core/remote_input/presence.py` | Изменён | Реализован адаптер `RedisPresenceRegistry` с персистентностью presence, inventory и stream параметров в Redis. |
| `app-service/core/diagnostics/sessions.py` | Изменён | Реализован `RedisDiagnosticsSessionRegistry` с персистентностью сессий диагностики в Redis (`l4d:diag:session:*`). |
| `app-service/create_api_app.py` | Изменён | Встроен запуск и корректная остановка пула соединений Redis в `lifespan`. |
| `app-service/tests/conftest.py` | Изменён | Подключена изоляция Redis в тестовой среде (встроенный in-memory `fakeredis`). |
| `app-service/tests/core/test_l4d_redis_registries.py` | Создан | Специализированный набор тестов для Redis: атомарность, продление, конфликты, гонки, очистка TTL, холодный рестарт, отказ соединений, Pub/Sub. |
| `docs/l4desk/handoffs/L4D-REDIS-IOT-01-report.md` | Создан | Настоящий handoff-отчёт. |
| `docs/l4desk/handoffs/L4D-REDIS-IOT-01-candidate.md` | Создан | Кандидатский блок в формате `DETACHED_V1`. |

---

## 4. Верификация, тестирование и статический анализ

### Результаты автоматических тестов (`pytest`)
- Команда запуска: `uv run pytest`
- **Общий итог**: **415 passed, 0 failed, 1 warning in 65.41s** (100% зелёный прогон).
- Вновь разработанные тесты (`app-service/tests/core/test_l4d_redis_registries.py`):
  - `test_redis_lease_acquire_and_touch_atomicity`: Проверка создания ключей `l4d:lease:*` и `l4d:lease:active:*`, TTL и продления — **PASSED**.
  - `test_redis_lease_conflict_and_race_prevention`: Проверка взаимного исключения и бесконфликтного перезахвата — **PASSED**.
  - `test_redis_lease_expiration_and_auto_cleanup`: Проверка отзыва просроченных лизов и удаления указателей — **PASSED**.
  - `test_redis_presence_and_inventory_recovery_after_restart`: Полная эмуляция холодного перезапуска приложения с мгновенным чтением данных из Redis — **PASSED**.
  - `test_redis_connection_error_handling`: Проверка корректного проброса `RedisConnectionError` и запрета неявных локальных дубликатов — **PASSED**.
  - `test_redis_lease_revocation_pubsub`: Проверка доставки события отзыва лиза через канал `l4d:pubsub:lease_revoked` — **PASSED**.

### Результаты статического анализа и линтеров
- Линтер: `uv run ruff check app-service/core/config.py app-service/core/redis_helper.py app-service/core/remote_input/leases.py app-service/core/remote_input/presence.py app-service/core/diagnostics/sessions.py app-service/create_api_app.py app-service/tests/conftest.py app-service/tests/core/test_l4d_redis_registries.py`
  - **Итог**: `All checks passed!` (0 errors).
- Форматирование: `uv run ruff format --check app-service/core/config.py app-service/core/redis_helper.py app-service/core/remote_input/leases.py app-service/core/remote_input/presence.py app-service/core/diagnostics/sessions.py app-service/create_api_app.py app-service/tests/conftest.py app-service/tests/core/test_l4d_redis_registries.py`
  - **Итог**: `8 files already formatted`.

---

## 5. Деплой и Smoke-проверка на сервере

1. Кодовые изменения отправлены в ветку `l4desk/l4d-redis-iot-01` (`producer_commit: 1745074e5ad5a4bfae6741743f05db5ef32095f9`).
2. По регламенту `docs/manual-app1-deploy-runbook.md` на стенде `user1@87.242.100.34`:
   ```bash
   cd /home/user1/iot-rpc-rest-app
   git fetch origin && git checkout l4desk/l4d-redis-iot-01 && git pull --ff-only
   cd /home/user1
   sudo docker compose build app1
   sudo docker compose up -d --no-deps app1
   ```
3. Процедура smoke-верификации:
   - Проверка логов `app1`:
     `sudo docker compose logs --tail=50 app1`
     Ожидается: `Redis connection pool initialized.`
   - Создание тестового лиза и проверка ключей в Redis:
     `sudo docker compose exec -T redis redis-cli -n 0 KEYS "l4d:*"`
     Ожидаются ключи префиксов `l4d:lease:`, `l4d:lease:active:`, `l4d:presence:`, `l4d:inventory:`.
   - Рестарт `app1` (`sudo docker compose restart app1`) и подтверждение чтения активных лизов и статуса присутствия без потерь.

---

## 6. Rollback-план

В случае непредвиденных инцидентов откат выполняется возвратом на предыдущий подтверждённый коммит сервиса:
```bash
cd /home/user1/iot-rpc-rest-app
git checkout c4e892f4c1dbf8f967109e8a06c3f63b0c9bd483
cd /home/user1
sudo docker compose build app1
sudo docker compose up -d --no-deps app1
```
Сервис вернётся в режим работы с in-memory хранилищем, внешние контракты и данные PostgreSQL останутся интактными.
