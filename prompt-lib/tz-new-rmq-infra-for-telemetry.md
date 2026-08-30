### Архитектурная спецификация и техническое задание: Инфраструктура RabbitMQ для Gauges (Leo4 ⇄ etranprocessing)

---

### 1. Разделение зон ответственности (Responsibility Boundary)

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 ЗОНА ОТВЕТСТВЕННОСТИ LEO4                              │
│  - Управление контейнером RabbitMQ, версиями, плагинами и `rabbitmq.conf`              │
│  - Настройка сетевых слушателей (Listeners: 8883 mTLS, 5672 AMQP, 1883 plain MQTT)     │
│  - Конфигурация Docker-сетей и выдача доступа для контейнеров `etranprocessing`        │
│  - Управление сервисным пользователем `etran_service`, vhost и topic permissions       │
│  - Гарантия сохранности runtime-конфигураций (volume `rabbitmq_data`, definitions)     │
│  - НИКАКОЙ бизнес-логики Gauges / парсинга телеметрии в кодовой базе Leo4              │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ Сетевая шина (Docker Bridge / AMQP & MQTT)
┌───────────────────────────────────────────▼────────────────────────────────────────────┐
│                           ЗОНА ОТВЕТСТВЕННОСТИ ETRANPROCESSING                         │
│  - Прием HTTP-запросов `POST /api/gategauge` от терминалов                             │
│  - Расчет 12-тактовой скользящей битовой маски (10-минутные интервалы)                 │
│  - Обогащение снимка метаданными (платежи, инкассация, лицензии, LWT)                  │
│  - Публикация и подписка на Retain-топики через выданные реквизиты                     │
│  - Отдача оперативного состояния в UI `GET /api/monitoring` без обращения к БД         │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

### 2. Техническое задание для Leo4: Развертывание инфраструктуры

#### 2.1. Сетевая топология Docker (`compose.yaml`)
Необходимо обеспечить сетевую связность между сервисами `etranprocessing` и контейнером `rabbitmq`.

1. В `compose.yaml` проекта Leo4 сеть `rabbitmq_network` объявляется как общая (либо создается внешняя сеть):
   ```yaml
   networks:
     rabbitmq_network:
       name: iot_rabbitmq_network
       driver: bridge
   ```
2. Сервисы `etranprocessing` подключаются к этой сети как к внешней (`external: true`).

#### 2.2. Конфигурация слушателей RabbitMQ (`rmq/rabbitmq.conf`)
Включить внутренний plain MQTT слушатель для локального межсервисного взаимодействия без накладных расходов на TLS-сертификаты.

Внести изменения в `rmq/rabbitmq.conf`:
```ini
# 1. AMQP Слушатель (для FastStream / aio-pika бэкенда)
listeners.tcp.default = 5672

# 2. Внешний mTLS MQTT Слушатель (Терминалы - БЕЗ ИЗМЕНЕНИЙ)
mqtt.listeners.ssl.default = 8883
ssl_options.cacertfile = /crt/ca_certificate.pem
ssl_options.certfile   = /crt/server_certificate.pem
ssl_options.keyfile    = /crt/server_key.pem
ssl_options.verify     = verify_peer
ssl_options.fail_if_no_peer_cert = true
mqtt.ssl_cert_login    = true

# 3. ВНУТРЕННИЙ Plain MQTT Слушатель (для сервисов внутри Docker-сети)
mqtt.listeners.tcp.default = 1883
mqtt.allow_anonymous = false
mqtt.vhost = /
mqtt.exchange = amq.topic
mqtt.max_session_expiry_interval_seconds = 86400
```
> **Важно:** Порт `1883` **НЕ** пробрасывается в секцию `ports:` хоста в `compose.yaml`, оставаясь доступным строго внутри Docker-сети `rabbitmq_network`.

#### 2.3. Создание сервисного пользователя и ACL (`definitions.json`)
Для изоляции доступа создается сервисный пользователь `etran_service`.

В `rmq/definitions.json` (и/или через модуль сидинга Leo4) добавляются:

1. **Пользователь:**
   ```json
   {
     "name": "etran_service",
     "password_hash": "<SHA256_HASH_FOR_ETRAN_SECRET>",
     "hashing_algorithm": "rabbit_password_hashing_sha256",
     "tags": []
   }
   ```
2. **Базовые разрешения на vhost `/`:**
   ```json
   {
     "user": "etran_service",
     "vhost": "/",
     "configure": "",
     "write": "^(amq\\.topic|telemetry\\..*)",
     "read": "^(amq\\.topic|telemetry\\..*)"
   }
   ```
3. **Topic Permissions на exchange `amq.topic`:**
   ```json
   {
     "user": "etran_service",
     "vhost": "/",
     "exchange": "amq.topic",
     "write": "^dev\\..*\\.gauge\\..*",
     "read": "^dev\\..*\\.gauge\\..*"
   }
   ```

#### 2.4. Регламент безопасного деплоя (Zero Downtime / Zero Config Loss)
Для предотвращения потери runtime-состояний устройств и накопленных MQTT-сессий:
1. **Категорически запрещено** выполнять `docker compose down -v` или удалять том `rabbitmq_data`.
2. Порядок применения обновления:
   ```bash
   # 1. Проверка валидности конфигурации
   docker compose exec rabbitmq rabbitmq-diagnostics check_running

   # 2. Перезапуск RabbitMQ с сохранением томов
   docker compose up -d --no-deps rabbitmq

   # 3. Верификация портов и слушателей
   docker compose exec rabbitmq rabbitmq-diagnostics listeners
   ```

---

### 3. Спецификация интеграции для etranprocessing (Контракт шины)

#### 3.1. Параметры подключения
* **Хост:** `rabbitmq` (внутри docker-сети `iot_rabbitmq_network`)
* **AMQP Port:** `5672` (протокол AMQP 0-9-1)
* **MQTT Port:** `1883` (протокол MQTT 3.1.1 / 5.0, TCP Plain)
* **Virtual Host:** `/`
* **Credentials:** логин `etran_service`, пароль задается через `.env` (`RABBITMQ_ETRAN_PASSWORD`).

#### 3.2. Топики и маршрутизация (Topic Contract)
В соответствии с механизмом RabbitMQ MQTT Plugin топики транслируются между MQTT и AMQP:

| Канал / Протокол | Формат топика / Routing Key | Режим доставки | Назначение |
|---|---|---|---|
| **MQTT** | `dev/{SN}/gauge/state` | `retain = true`, `QoS = 1` | Снимок актуального состояния датчиков и 12-битного регистра |
| **AMQP 0-9-1** | Exchange: `amq.topic`<br>Routing Key: `dev.{SN}.gauge.state` | Durable / Persistent | Доступ к тем же событиям через AMQP-клиенты (`aio-pika`, `faststream`) |

#### 3.3. Спецификация Payload (Materialized Snapshot JSON Schema)
Сообщение, удерживаемое в retain-топике `dev/{SN}/gauge/state`:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "DeviceGaugeSnapshot",
  "type": "object",
  "required": ["device_id", "sn", "updated_at", "last_tick_epoch", "slots_bitmask", "gauge"],
  "properties": {
    "device_id": { "type": "integer", "description": "Идентификатор устройства в платформе" },
    "sn": { "type": "string", "description": "Серийный номер устройства" },
    "updated_at": { "type": "string", "format": "date-time", "description": "ISO 8601 отметка последнего запроса GateGauge" },
    "last_tick_epoch": { "type": "integer", "description": "Номер 10-минутного интервала Unix-эпохи (epoch_seconds // 600)" },
    "slots_bitmask": { "type": "integer", "minimum": 0, "maximum": 4095, "description": "12-битное число, представляющее такты от now до now-120min" },
    "gauge": {
      "type": "object",
      "description": "Сырые и нормализованные параметры датчиков",
      "properties": {
        "validator_state": { "type": "string" },
        "validator_type": { "type": "integer" },
        "cash_amount": { "type": "integer" },
        "printer_state": { "type": "string" },
        "printer_fr": { "type": "integer" },
        "printer_check_counter": { "type": "integer" },
        "soft_version": { "type": "string" }
      }
    },
    "internal_enrichment": {
      "type": "object",
      "description": "Обогащение из внутренних доменных моделей",
      "properties": {
        "last_payment_at": { "type": ["string", "null"], "format": "date-time" },
        "last_inkass_at": { "type": ["string", "null"], "format": "date-time" },
        "license_expires_at": { "type": ["string", "null"], "format": "date-time" },
        "iot_is_online": { "type": "boolean" }
      }
    }
  }
}
```

#### 3.4. Логика работы `etranprocessing` с шиной
1. **Прием запроса (`POST /api/gategauge`):**
   * Вычисляется текущий такт `current_tick = int(now // 600)`.
   * Из локального in-memory кэша (синхронизированного с RabbitMQ) извлекается текущий `slots_bitmask`.
   * Выполняется сдвиг: `slots_bitmask = ((slots_bitmask << delta) & 0x0FFF) | 1`.
   * Формируется обновленный JSON-снимок.
   * Выполняется `PUBLISH` в топик `dev/{SN}/gauge/state` с флагом `retain=true` (через порт 1883 или 5672).
2. **Инициализация / Старт `etranprocessing`:**
   * Сервис подписывается на шаблон `dev/+/gauge/state`.
   * Брокер мгновенно выгружает все сохраненные retain-слепки.
   * Локальная in-memory таблица готова к обслуживанию `GET /api/monitoring` без SQL-запросов к телеметрии.

---

### 4. Критерии приемки (Definition of Done)

1. **Для Leo4:**
   * В логах RabbitMQ подтвержден запуск слушателей: `8883 (SSL)`, `5672 (TCP)`, `1883 (TCP)`.
   * Пользователь `etran_service` создан и успешно проходит аутентификацию на портах `5672` и `1883`.
   * Сеть `iot_rabbitmq_network` доступна для подключения сторонних контейнеров.
   * Существующие mTLS-подключения терминалов и сессии не затронуты.
2. **Для etranprocessing:**
   * Реализован коннектор к порту 1883/5672 с реквизитами `etran_service`.
   * Успешно отправляются и вычитываются тестовые Retain-сообщения по топикам `dev/{SN}/gauge/state`.
   * Эндпоинт `/api/monitoring` отдает 12-битные слоты и параметры датчиков из оперативного кэша.