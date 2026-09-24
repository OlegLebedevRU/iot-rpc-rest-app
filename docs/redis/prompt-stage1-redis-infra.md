# Задание: Инфраструктурное развёртывание Redis (Этап 1, обратно совместимый с `main`)

## 1. Роль, репозиторий и системные границы

Ты — DevOps / Backend инженер платформы `iot-rpc-rest-app`.  
Рабочий репозиторий: **`D:\work\iot.leo4.ru\iot-rpc-rest-app`**.  
Стенд развёртывания: **`user1@87.242.100.34`** (каталог на сервере `/home/user1/iot-rpc-rest-app`, оркестратор `/home/user1/compose.yaml`).

### Главная цель задания:
Реализовать **Этап 1** внедрения Redis — автономный, изолированный инфраструктурный шаг, который:
1. Разворачивает персистентный контейнер Redis (`iot-redis`) на сервере `87.242.100.34`.
2. Является **на 100% обратно совместимым с веткой `main`** и текущей рабочей веткой (не ломает запуск `app1`, не требует переменных окружения для старта старых образов).
3. Готовит инфраструктуру для смежных проектов (`MenuBuilder`, `l4media`, сервисы телеметрии), предоставляя им выделенные базы данных (`DB 1`, `DB 2`, `DB 3`) без задержек на доработку кода `iot-rpc-rest-app`.

### Границы задачи (Scope & Out-of-Scope):
- **Входит в задачу (Scope)**:
  - Создание директории `redis/` и системного файла конфигурации `redis/redis.conf`.
  - Модификация `compose.yaml`: объявление сервиса `redis`, тома `redis_data`, сети `redis_network`, проброс порта на `127.0.0.1:6379`.
  - Добавление настроек в `app-service/.env.template`.
  - Создание руководства интегратора для смежных проектов `docs/redis/redis-integration-guide.md`.
  - Актуализация регламента деплоя `docs/manual-infra-and-rmq-deploy-runbook.md`.
  - Деплой и smoke-тестирование сервиса `redis` на целевом сервере.
- **СТРОГО ЗА ПРЕДЕЛАМИ (Out-of-Scope)**:
  - Изменение прикладного Python-кода в `app-service/` (перенос сессий и лизов в Redis выполняется на последующих этапах 2, 3 и 4).
  - Добавление `depends_on: redis` в сервис `app1` (в ветке `main` сервис `app1` должен оставаться полностью автономным).
  - Перезапуск или модификация контейнеров `pg`, `rabbitmq`, `nginx`, `nginx-mutual` или `app1`.

---

## 2. Пошаговый план реализации в репозитории

### Шаг 1. Создание системной конфигурации `redis/redis.conf`
Создать каталог `redis/` в корне проекта и разместить конфигурационный файл `redis/redis.conf`:

```text
# Сетевой интерфейс внутри контейнера (доступен из docker-сетей)
bind 0.0.0.0
port 6379
protected-mode no
tcp-backlog 511
timeout 0
tcp-keepalive 300

# Режим персистентности (AOF + RDB) для гарантии сохранности данных при авариях
appendonly yes
appendfilename "appendonly.aof"
appenddirname "appendonlydir"
appendfsync everysec
no-appendfsync-on-rewrite no
auto-aof-rewrite-percentage 100
auto-aof-rewrite-min-size 64mb

# Снимки RDB для быстрого восстановления и удобства резервного копирования
save 900 1
save 300 10
save 60 10000
rdbcompression yes
rdbchecksum yes
dbfilename dump.rdb
dir /data

# Управление памятью и защита от OOM
maxmemory 1gb
maxmemory-policy volatile-lru

# Логирование
loglevel notice
logfile ""
```

### Шаг 2. Модификация `compose.yaml`
В корневой файл `compose.yaml` внести следующие изменения:

1. В секцию `services:` добавить блок сервиса `redis`:
```yaml
  redis:
    image: redis:7.4-alpine
    container_name: iot-redis
    restart: unless-stopped
    command: ["redis-server", "/usr/local/etc/redis/redis.conf"]
    volumes:
      - redis_data:/data
      - ./redis/redis.conf:/usr/local/etc/redis/redis.conf:ro
    ports:
      # Проброс строго на loopback хоста для смежных сервисов хоста
      - "127.0.0.1:6379:6379"
    networks:
      - rabbitmq_network # Межсервисная сеть iot_rabbitmq_network
      - redis_network
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 3
```
2. Для сервиса `app1` в секцию `networks:` добавить `redis_network` (для будущей связи). **НЕ добавлять** `redis` в `depends_on:`, чтобы не блокировать автономный запуск `app1` из ветки `main`.
3. В секцию `volumes:` добавить:
```yaml
  redis_data:
    driver: local
```
4. В секцию `networks:` добавить:
```yaml
  redis_network:
    name: iot_redis_network
    driver: bridge
```

### Шаг 3. Актуализация `app-service/.env.template`
В файл `app-service/.env.template` добавить секцию конфигурации:
```bash
# Redis (L4D persistent sessions, locks, cache)
# DB 0: iot-rpc-rest-app / l4desk
APP_CONFIG__REDIS__URL=redis://127.0.0.1:6379/0
```

### Шаг 4. Создание руководства интегратора `docs/redis/redis-integration-guide.md`
Создать файл `docs/redis/redis-integration-guide.md`, описывающий для разработчиков `MenuBuilder`, `l4media` и сервисов телеметрии:
- Назначение баз данных (`DB 0` — IoT/L4D, `DB 1` — MenuBuilder, `DB 2` — l4media, `DB 3` — телеметрия).
- Строки подключения:
  - Внутри Docker-сети: `redis://redis:6379/<db>`
  - С хоста: `redis://127.0.0.1:6379/<db>`
- Префиксы ключей (`mb:*`, `media:*`, `proc:*`).
- Правило: использовать `TTL` для временных сессионных данных и кэша во избежание переполнения памяти.

### Шаг 5. Обновление `docs/manual-infra-and-rmq-deploy-runbook.md`
Добавить раздел по процедуре запуска, диагностики и резервного копирования сервиса `redis`:
- Команда запуска: `sudo docker compose up -d redis`.
- Проверка статуса: `sudo docker compose ps redis` и `redis-cli ping`.
- Резервное копирование: сохранение каталога тома `/var/lib/docker/volumes/..._redis_data/_data`.

---

## 3. Регламент деплоя и верификации на целевом сервере

Все действия выполняются через неинтерактивный SSH в соответствии с регламентом `docs/manual-infra-and-rmq-deploy-runbook.md`:

```powershell
$script = @'
set -euo pipefail
cd /home/user1

echo "=== 1. Проверка текущих сервисов (до деплоя) ==="
sudo docker compose ps

echo "=== 2. Синхронизация манифестов ==="
# Синхронизация compose.yaml и каталога redis/
# (выполняется через git pull или scp)

echo "=== 3. Запуск сервиса Redis ==="
sudo docker compose up -d redis

echo "=== 4. Проверка состояния контейнера ==="
sudo docker compose ps redis

echo "=== 5. Проверка отклика Redis (Ping-Pong) ==="
sudo docker compose exec -T redis redis-cli ping

echo "=== 6. Проверка доступности порта на 127.0.0.1 хоста ==="
python3 -c "import socket; s = socket.create_connection(('127.0.0.1', 6379), timeout=2); s.sendall(b'PING\r\n'); print(s.recv(1024).decode())"

echo "=== 7. Проверка персистентности данных (AOF/RDB) ==="
sudo docker compose exec -T redis redis-cli SET "test:smoke_key" "ok_stage_1"
sudo docker compose restart redis
RESULT=$(sudo docker compose exec -T redis redis-cli GET "test:smoke_key")
if [ "$RESULT" != "ok_stage_1" ]; then
    echo "ERROR: Redis persistence failed!"
    exit 1
fi
sudo docker compose exec -T redis redis-cli DEL "test:smoke_key"
echo "=== Redis Stage 1 Deploy Verified Successfully ==="
'@

$script | ssh -n -i "d:\.ssh\id_ed25519" -o BatchMode=yes user1@87.242.100.34 "bash -s"
```

---

## 4. Стратегия коммитов и интеграции в ветки

1. **Создание инфраструктурного коммита**:
   - Включить файлы: `redis/redis.conf`, `compose.yaml`, `app-service/.env.template`, `docs/redis/redis-integration-guide.md`, `docs/manual-infra-and-rmq-deploy-runbook.md`.
   - Сообщение коммита:
     ```text
     feat(infra): deploy redis service for persistent sessions and shared caching

     - Add redis:7.4-alpine service to compose.yaml with redis_data volume
     - Add redis.conf with hybrid persistence (AOF everysec + RDB)
     - Bind port to 127.0.0.1:6379 to ensure internal security
     - Add redis-integration-guide.md for MenuBuilder and l4media delegation
     - Preserve full backward compatibility with main branch
     ```
2. **Вливание в ветку `main`**:
   - Замержить изменения в `main`. Убедиться, что CI проходит без замечаний.
3. **Синхронизация с текущей рабочей веткой**:
   - Выполнить `git merge main` в рабочей ветке L4D.

---

## 5. Критерии приёмки (Definition of Done)

- [ ] Файл `redis/redis.conf` создан и содержит валидную конфигурацию (персистентность AOF+RDB, лимит 1 ГБ, режим `volatile-lru`).
- [ ] Сервис `redis` добавлен в `compose.yaml`, подключён к `rabbitmq_network` и `redis_network`, порт привязан строго к `127.0.0.1:6379`.
- [ ] Сервис `app1` в `compose.yaml` не имеет блокирующей зависимости `depends_on: redis` и собирается/запускается независимо.
- [ ] Создано руководство интегратора `docs/redis/redis-integration-guide.md`.
- [ ] Регламент `docs/manual-infra-and-rmq-deploy-runbook.md` актуализирован.
- [ ] На целевом сервере контейнер `iot-redis` поднят, `healthcheck` находится в статусе `healthy`, ping возвращает `PONG`.
- [ ] Проверено сохранение тестового ключа при перезапуске контейнера `redis`.
- [ ] Сервисы `app1`, `rabbitmq`, `pg`, `nginx` продолжают работать без перезапуска и прерываний.
- [ ] Изменения успешно влиты в ветку `main` и синхронизированы с текущей веткой.
