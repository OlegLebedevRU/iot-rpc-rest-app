Ниже представлен итоговый рабочий промпт, полностью адаптированный под зарегистрированную контроллером запись `R-L4D-REDIS-IOT-01-v1`, правила стандарта `PROMPT-STANDARD.md` (версия 1.2.0, разделы 8 и 9 `DETACHED_V1`), а также ограничения изолированного внедрения в `iot-rpc-rest-app`.

---

# L4D-REDIS-IOT-01 — Внедрение постоянного хранения оперативных сессий и Presence в Redis

```yaml
prompt_id: L4D-REDIS-IOT-01
registration_id: R-L4D-REDIS-IOT-01-v1
scope_project: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
prompt_type: implementation-provider
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
branch: l4desk/l4d-redis-iot-01
report_path: docs/l4desk/handoffs/L4D-REDIS-IOT-01-report.md
candidate_path: docs/l4desk/handoffs/L4D-REDIS-IOT-01-candidate.md
candidate_format: DETACHED_V1
architecture_sections: [3, 4, 5, 6, 8, 11, 12, 16, 17]
```


## 1. Роль, границы и системная цель

Ты — Backend Developer сервиса `app1` платформы `iot-rpc-rest-app`.  
Рабочий репозиторий: **`D:\work\iot.leo4.ru\iot-rpc-rest-app`**.  
Стенд развёртывания: **`user1@87.242.100.34`** (каталог `/home/user1/iot-rpc-rest-app`, оркестратор `/home/user1/compose.yaml`).

### Главная цель:
Перевести оперативное состояние удалённого ввода (`LeaseRegistry`), оперативное присутствие терминалов (`PresenceRegistry`) и сессии диагностики (`DiagnosticsSessionRegistry`) из in-memory структур процесса в распределённое хранилище **Redis (`DB 0`)**, сохранив непрерывность сессий оператора при перезапусках `app1` и **строго 100% обратную совместимость всех внешних контрактов**.

### Строгие границы (Scope & Invariants):
1. **Этап 1 инфраструктуры уже развернут**: контейнер `iot-redis` поднят на сервере, порт `127.0.0.1:6379` доступен, сеть `iot_redis_network` настроена. Повторный деплой инфры Redis не требуется.
2. **СТРОГИЙ ЗАПРЕТ на изменение внешних контрактов**:
   - Никаких изменений сигнатур REST API (`/api/internal/v1/*`, `/api/v1/*`), WebSocket-протоколов, топиков MQTT (`srv/<SN>/*`, `dev/<SN>/*`), кодов методов (`7000`, `7001`, `7002`), wire-протокола `L4RTP/1` или схемы durable event feed `02`.
   - Не менять поведение для клиентов `MenuBuilder`, `l4media` и `tools` (Агент).
3. **Единственный источник постоянных фактов — PostgreSQL**:
   - Таблицы `tb_remote_sessions` и `tb_remote_session_events` остаются единственным источником финансового и технического аудита. Redis используется строго как быстрый оперативный кэш/реестр.
4. **Сохранение режима `WEB_CONCURRENCY=1`**:
   - Не включать multi-worker режим на проде без отдельной валидации распределённых мьютексов.
5. **Все файлы `l4desk-service/` в репозитории — Read-Only**:
   - Все отчёты и кандидатские блоки создавать исключительно внутри `docs/l4desk/handoffs/`.

---

## 2. Contract Gate (Обязательное первое действие)

1. Открой `l4desk-service/docs/prompts/contract-handoff.md` в режиме read-only.
2. Проверь наличие регистрации `R-L4D-REDIS-IOT-01-v1` со статусом `AUTHORIZED`.
3. Проверь принятые sequence gate `H-L4D-07-IOT-v1` и входной handoff `H-L4D-02-IOT-v1`:
   - Убедись, что блоки имеют статус `ACCEPTED`.
   - Проверь совпадение SHA-256 артефактов `H-L4D-07-IOT-v1` и `H-L4D-02-IOT-v1`.
4. Зафиксируй входные метаданные во вводной части отчёта `docs/l4desk/handoffs/L4D-REDIS-IOT-01-report.md`.

---

## 3. Пошаговый план реализации

### Шаг 1. Клиентский слой Redis в `app-service`
1. Подключи асинхронный драйвер Redis: `uv add redis` (если ещё не зафиксирован в `pyproject.toml` / `uv.lock`).
2. В `app-service/core/config.py` убедись в наличии настройки `APP_CONFIG__REDIS__URL` (по умолчанию `redis://127.0.0.1:6379/0` на хосте и `redis://redis:6379/0` в docker).
3. Реализуй модуль управления пулом соединений `app-service/core/redis_helper.py` (или `app-service/core/redis.py`):
   - Инициализация и закрытие пула в `lifespan` (`app-service/create_api_app.py`).
   - Функция проверки здоровья `ping()`.
   - Корректная обработка `ConnectionError` (отказ не должен приводить к тихой генерации дублирующих лизов).

### Шаг 2. Реализация `RedisLeaseRegistry`
1. В `app-service/core/remote_input/leases.py` реализуй адаптер `RedisLeaseRegistry` под существующий протокол `LeaseRegistryProtocol`:
   - Сохранение `Lease` в Redis Hash `l4d:lease:<lease_id>` с TTL `ttl_sec + 30s`.
   - Указатель активного лиза устройства `l4d:lease:active:<sn>` со строгим TTL.
   - Атомарный захват/продление/освобождение (использовать Redis-транзакции `pipeline` или Lua-скрипт).
   - Проверка владельца (`owner_user_id`) при попытке освобождения лиза.
   - Публикация в Redis Pub/Sub канал `l4d:pubsub:lease_revoked` при досрочном отзыве.

### Шаг 3. Реализация `RedisPresenceRegistry`
1. В `app-service/core/remote_input/presence.py` реализуй адаптер `RedisPresenceRegistry` под `PresenceRegistryProtocol`:
   - Состояние агента `l4d:presence:<sn>` (Hash с TTL 90 сек).
   - Снимок инвентаря мониторов `l4d:inventory:<sn>` (JSON с TTL 24 ч).
   - Параметры стрима `l4d:stream:<sn>` (TTL синхронен со стримом).
   - При рестарте `app1` инвентарь и онлайн-статус должны восстанавливаться мгновенно из Redis.

### Шаг 4. Реестр сессий диагностики `RedisDiagnosticsRegistry`
1. В `app-service/core/diagnostics/sessions.py` реализуй персистентность активных сессий потокового вывода консоли (`dev/<SN>/out`) в Redis (ключи `l4d:diag:session:<session_id>` с TTL `ttl_sec`).

---

## 4. Тестирование и верификация (Definition of Done)

До деплоя и коммита выполни исчерпывающие проверки:
1. **Unit & Integration тесты**:
   - Напиши сьют тестов `app-service/tests/core/test_l4d_redis_registries.py`, проверяющий:
     - Атомарность захвата и продления лиза.
     - Корректное истечение TTL и авто-освобождение.
     - Сохранение и восстановление лизов/presence при эмуляции перезапуска приложения.
     - Защиту от гонок и повторных вызовов на одном `sn`.
     - Корректную отработку `ConnectionError`.
   - Прогони весь существующий тестовый сьют проекта: `uv run pytest` (все 400+ тестов обязаны пройти зелёными).
2. **Статический анализ и линтинг**:
   - `uv run ruff check .`
   - `uv run ruff format --check .`
   - `uv run pyright` (0 errors, 0 warnings).

---

## 5. Деплой и Smoke-проверка на сервере

1. Выполни commit и push в ветку `l4desk/l4d-redis-iot-01`:
   - Включай **только** файлы проекта `iot-rpc-rest-app`.
2. По регламенту `docs/manual-app1-deploy-runbook.md` выполни деплой сервиса `app1` на стенд `user1@87.242.100.34`:
```shell script
cd /home/user1/iot-rpc-rest-app
   git fetch origin && git checkout l4desk/l4d-redis-iot-01 && git pull --ff-only
   cd /home/user1
   sudo docker compose build app1
   sudo docker compose up -d --no-deps app1
```

3. **Smoke-верификация на хосте**:
   - Проверь логи `app1` на отсутствие ошибок подключения к Redis: `sudo docker compose logs --tail=50 app1`.
   - Создай тестовый лиз через внутренний API и проверь его наличие в Redis:
     `sudo docker compose exec -T redis redis-cli -n 0 KEYS "l4d:*"`
   - Перезапусти `app1` (`sudo docker compose restart app1`) и убедись, что созданный лиз и presence сохранились и читаются.

---

## 6. Отчётность и протокол DETACHED_V1 для контроллера

Так как регистрация `R-L4D-REDIS-IOT-01-v1` утвердила формат `DETACHED_V1`:

1. **Создай и опубликуй отчёт реализации**:
   - Путь: `docs/l4desk/handoffs/L4D-REDIS-IOT-01-report.md`.
   - Включи результаты тестов, линтеров, commit SHA, вывод smoke-проверок с сервера и rollback-план.
   - Закоммить отчёт в ветку (`commit R`).
   - Вычисли контрольную сумму SHA-256 опубликованного файла отчёта.
2. **Создай отдельный кандидатский файл**:
   - Путь: `docs/l4desk/handoffs/L4D-REDIS-IOT-01-candidate.md`.
   - Включи YAML-блок `HANDOFF:H-L4D-REDIS-IOT-01-v1` с `status: CANDIDATE`, перечнем всех изменённых файлов в `artifact_paths`, их SHA-256 и хешем отчёта (из коммита R).
   - Закоммить кандидат отдельным коммитом (`commit C`).
3. **Передай контроллеру каскада финальное уведомление**:
   - **Абсолютный путь к отчёту**: `D:\work\iot.leo4.ru\iot-rpc-rest-app\docs\l4desk\handoffs\L4D-REDIS-IOT-01-report.md`
   - **Абсолютный путь к кандидату**: `D:\work\iot.leo4.ru\iot-rpc-rest-app\docs\l4desk\handoffs\L4D-REDIS-IOT-01-candidate.md`
   - SHA-256 кандидата и отчёта.
   - Коммиты `producer_commit` (код), `report_commit` (отчёт) и `candidate_commit` (кандидат).
   - Запрос на append-only добавление принятого блока в `contract-handoff.md`.