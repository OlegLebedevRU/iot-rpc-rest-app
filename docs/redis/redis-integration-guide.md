# Руководство по интеграции с Redis (Leo4 IoT Platform & L4Desk)

**Статус:** Действующий регламент (Этап 1 — Инфраструктурное развёртывание)  
**Контейнер:** `iot-redis` (образ `redis:7.4-alpine`)  
**Оркестрация:** Docker Compose (`compose.yaml` в корне проекта и `/home/user1/compose.yaml` на сервере)

---

## 1. Назначение и архитектурная роль

Сервис **Redis** развёрнут в составе единой инфраструктуры Leo4 IoT Platform для обеспечения:
- Персистентного хранения сессий удалённого управления L4Desk (`l4desk-service`);
- Распределённых блокировок (leases) терминалов и управления состоянием присутствия (presence);
- Высокопроизводительного разделяемого кэширования для сервисов `MenuBuilder`, `l4media`, `ProcessingBackend` и телеметрии;
- Разгрузки PostgreSQL и RabbitMQ от частых запросов опроса состояний.

---

## 2. Распределение логических баз данных (Database Allocation)

Для предотвращения коллизий ключей между микросервисами используется строгое разделение по логическим базам данных Redis:

| Номер DB | Владелец / Сервис | Назначение и типы данных | Рекомендуемый TTL |
|:---:|:---|:---|:---|
| **`DB 0`** | `iot-rpc-rest-app` / `l4desk` | Активные сессии L4D, лизы терминалов, кэш статусов устройств, remote input presence | 30 сек – 24 ч (по типу сессии) |
| **`DB 1`** | `MenuBuilder` | Кэш entitlement, балансов, временные токены сессий UI, кэш меню | 5 мин – 2 ч |
| **`DB 2`** | `l4media` | Сигналинг WebRTC, временные SDP offer/answer, ICE-кандидаты, медиа-сессии | 10 сек – 5 мин |
| **`DB 3`** | `ProcessingBackend` / Telemetry | Кэш одноразовых PIN, верификация CSR, буферизация телеметрии | 1 мин – 15 мин |
| **`DB 4` – `DB 15`** | *Резерв* | Выделенные контуры для будущих подсистем и фоновых воркеров | По регламенту сервиса |

---

## 3. Сетевой доступ и строки подключения

### 3.1. Доступ из Docker-контейнеров
Все сервисы, входящие в состав docker-compose (находящиеся в сетях `user1_default`, `iot_rabbitmq_network` или `iot_redis_network`), обращаются к Redis по имени сервиса `redis`:

- **Базовый URL:** `redis://redis:6379/<db_number>`
- **Примеры:**
  - Для `iot-rpc-rest-app`: `redis://redis:6379/0`
  - Для `MenuBuilder`: `redis://redis:6379/1`
  - Для `l4media`: `redis://redis:6379/2`
  - Для `ProcessingBackend`: `redis://redis:6379/3`

### 3.2. Доступ с хоста (Localhost / Loopback)
Для процессов, запускаемых непосредственно на виртуальной машине вне Docker:

- **Базовый URL:** `redis://127.0.0.1:6379/<db_number>`

### 3.3. Сетевая безопасность
- Порт `6379` привязан **строго к `127.0.0.1`** на хосте (`127.0.0.1:6379:6379`).
- Внешний доступ из интернета закрыт на уровне сетевого сокета и firewall.
- Аутентификация по паролю во внутреннем защищённом контуре отключена для минимизации оверхеда на RTT.

---

## 4. Соглашение по именованию ключей (Key Namespaces)

Каждый сервис должен использовать стандартизованный префикс ключей даже внутри своей выделенной БД:

| Префикс | Владелец | Примеры ключей |
|:---|:---|:---|
| `l4d:*` / `iot:*` | `iot-rpc-rest-app` | `l4d:session:{session_id}`, `l4d:lease:{sn}`, `iot:presence:{sn}` |
| `mb:*` | `MenuBuilder` | `mb:entitlement:{tenant_id}`, `mb:user_token:{token_hash}` |
| `media:*` | `l4media` | `media:webrtc:{session_id}`, `media:peer:{peer_id}` |
| `proc:*` | `ProcessingBackend` | `proc:pin:{pin_code}`, `proc:csr:{csr_id}` |

---

## 5. Политика управления памятью и правила персистентности

### 5.1. Лимит памяти и OOM-защита
- Максимальный объём памяти инстанса: **1 ГБ** (`maxmemory 1gb`).
- Политика вытеснения: **`volatile-lru`** — при достижении лимита памяти автоматически удаляются наименее используемые ключи, **для которых установлен TTL**. Ключи без TTL сохраняются.

### 5.2. Золотое правило: Обязательный TTL
> ⚠️ **КРИТИЧЕСКОЕ ТРЕБОВАНИЕ ДЛЯ ИНТЕГРАТОРОВ:**  
> Все временные данные, сессионные маркеры, сигнальные сообщения WebRTC и записи кэша **ОБЯЗАНЫ** создаваться с явным указанием срока жизни (`TTL` / `EXPIRE` / `SET ... EX <seconds>`).  
> Запрещается создавать неограниченно растущие коллекции или постоянные ключи без TTL в разделяемом кэше во избежание сбоев `OOM`.

### 5.3. Персистентность (AOF + RDB)
- **AOF (Append-Only File):** включен в режиме `appendfsync everysec`, что гарантирует потерю не более 1 секунды данных в случае аварийной остановки сервера.
- **RDB (Snapshots):** сохранение снимков на диск при изменении 1 ключа за 900 сек, 10 ключей за 300 сек, 10000 ключей за 60 сек.
- Данные персистентно сохраняются в именованном Docker-томе `redis_data` (каталог внутри контейнера `/data`).

---

## 6. Примеры интеграции в коде (Python AsyncIO)

```python
import redis.asyncio as aioredis

# Инициализация пула подключений к нужной БД (например, DB 1 для MenuBuilder)
redis_client = aioredis.from_url(
    "redis://redis:6379/1",
    encoding="utf-8",
    decode_responses=True,
    max_connections=20,
)

async def set_cache_with_ttl(key: str, value: str, ttl_seconds: int = 300) -> None:
    # Всегда передаём параметр ex (TTL)
    await redis_client.set(f"mb:cache:{key}", value, ex=ttl_seconds)

async def get_cached_data(key: str) -> str | None:
    return await redis_client.get(f"mb:cache:{key}")
```

---

## 7. Мониторинг и эксплуатация

- Проверка статуса сервиса:
  ```bash
  sudo docker compose ps redis
  ```
- Проверка доступности (Ping-Pong):
  ```bash
  sudo docker compose exec -T redis redis-cli ping
  ```
- Просмотр статистики использования памяти и ключей:
  ```bash
  sudo docker compose exec -T redis redis-cli info memory
  sudo docker compose exec -T redis redis-cli info keyspace
  ```
