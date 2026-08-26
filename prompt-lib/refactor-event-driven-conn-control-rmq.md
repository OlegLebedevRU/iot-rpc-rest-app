### 1. Оценка архитектурного предложения

Переход на гибридную модель **Event-Driven State + Slow Reconciliation (Сверка раз в 10 мин)** — это **абсолютно правильное и эталонное решение** для production-систем IoT:

#### Почему это отлично работает:
1. **Мгновенная реактивность (Sub-second Latency)**: Задержка обновления статуса соединения в БД и UI снижается с интервала поллинга (30–60 с) до **миллисекунд** (время доставки AMQP-события `connection.created` / `connection.closed`).
2. **Снятие паразитной нагрузки с RabbitMQ**: HTTP Management API в RabbitMQ (на базе Erlang Mnesia) тяжело переносит частые опросы сотен и тысяч соединений. Увеличение интервала до 10 минут полностью устраняет нагрузку на CPU/RAM брокера.
3. **Гарантия согласованности (Reconciliation Loop)**: Периодический опрос раз в 10 минут остаётся как надёжная страховка (self-healing) на случай перезапуска бэкенда или сетевых аномалий.

---

### 2. Ключевые уточняющие моменты перед выполнением ТЗ

1. **Идентификация устройства в событии `amq.rabbitmq.event`**:
   - В событии `connection.created`/`connection.closed` Device SN содержится в поле `user` (при mTLS / basic auth) и/или в `client_properties.client_id`. Воркер должен проверять оба поля.
2. **Защита от Out-of-Order событий (Race Condition при быстром реконнекте)**:
   - Если устройство быстро переподключилось (flapping), событие `connection.closed` от старого сокета может прийти на долю секунды позже `connection.created` от нового.
   - *Решение*: проверять `timestamp` события или сравнивать имя/PID соединения: если текущее соединение новее закрывшегося, не сбрасывать статус в `false`.
3. **Холодный старт бэкенда (Cold Boot)**:
   - При старте приложения воркер выполняет один разовый опрос `GET /api/connections` для инициализации актуальной картины в памяти/БД, после чего переходит на чистый Event-Driven режим.

---

### 3. Полный детальный промпт для проекта `D:\work\iot.leo4.ru\iot-rpc-rest-app`

```markdown
### Техническое задание: Рефакторинг мониторинга DeviceConnections — Event-Driven архитектура (RabbitMQ Event Exchange) и оптимизация поллинга

#### 1. Цель и архитектура
Перевести мониторинг подключений терминалов (`DeviceConnections`) с частого синхронного поллинга RabbitMQ Management API на гибридную модель:
1. **Реактивный Event-Driven контур**: мгновенная обработка событий `connection.created` и `connection.closed` из Topic Exchange `amq.rabbitmq.event` (плагин `rabbitmq_event_exchange`).
2. **Мягкий фоновый контур сверки (Reconciliation Loop)**: опрос RabbitMQ Management API с увеличенным интервалом (10 минут) для неспешного сбора детальной сетевой телеметрии (`details`, ssl-информация, ip/port, socket metrics) и устранения возможных расхождений.
3. **Бизнес-логика статусов (Вариант 1 — Сохранение состояния процессов)**:
   - `last_checked_result` отражает физическое наличие mTLS-туннеля/сокета терминала к серверу (`connection.created` -> `true`, `connection.closed` -> `false`).
   - `app_connect` и `svc_connect` отражают состояние локальных процессов терминала и обновляются только через MQTT-топики LWT / Presence (`dev/{SN}/app`, `dev/{SN}/svc`). При обрыве связи они НЕ сбрасываются в `false`.
   - В API и UI доступность сервисов вычисляется как:
     `is_app_available = last_checked_result and app_connect`
     `is_svc_available = last_checked_result and svc_connect`

---

#### 2. Блок DevOps: Безопасное включение `rabbitmq_event_exchange` и бэкап
Перед внесением изменений выполнить безопасную процедуру без потери данных, очередей и настроек:

1. **Резервное копирование конфигураций и definitions**:
   ```bash
   # Экспорт всех очередей, пользователей, прав и bindings
   sudo docker exec <rabbitmq_container> rabbitmqadmin export /tmp/definitions_backup.json
   sudo docker cp <rabbitmq_container>:/tmp/definitions_backup.json ./rabbitmq_definitions_backup_$(date +%Y%m%d_%H%M%S).json
   
   # Сохранение списка включенных плагинов
   sudo docker exec <rabbitmq_container> rabbitmq-plugins list -e
   ```
2. **Включение плагина `rabbitmq_event_exchange`**:
   ```bash
   sudo docker exec <rabbitmq_container> rabbitmq-plugins enable rabbitmq_event_exchange
   ```
3. **Фиксация в конфигурации (персистентность при пересборке)**:
   - Убедиться, что в `enabled_plugins` (в docker-compose или монтируемом томе RabbitMQ) присутствует `rabbitmq_event_exchange`:
     ```text
     [rabbitmq_management,rabbitmq_mqtt,rabbitmq_event_exchange].
     ```
4. **Проверка**:
   - Убедиться, что появился exchange `amq.rabbitmq.event` типа `topic`.

---

#### 3. Блок Backend: Реализация `DeviceConnectionEventConsumer`

1. **Декларация AMQP очереди и топологии**:
   - Создать долговечную очередь (durable) `iot.device.connection.events` с аргументами:
     - `x-message-ttl` (например, 86400000 = 24 часа).
   - Привязать очередь к exchange `amq.rabbitmq.event` по routing keys:
     - `connection.created`
     - `connection.closed`

2. **Парсинг полезной нагрузки событий**:
   - Извлечь Device SN из входящего сообщения:
     ```python
     user = payload.get("user")
     client_id = payload.get("client_properties", {}).get("client_id")
     device_sn = user if (user and is_valid_device_sn(user)) else client_id
     ```
   - **Фильтрация**: игнорировать служебные подключения бэкенда (`guest`, `admin`, внутренние воркеры). Обрабатывать только клиентские подключения устройств.

3. **Обработка событий в БД (`DeviceConnections`)**:
   - **На `connection.created`**:
     - Найти/создать запись для `device_sn`.
     - Установить `last_checked_result = True`.
     - Обновить `last_checked_at = datetime.utcnow()`.
     - Сохранить ID активного соединения (`conn_id` / `conn_name`).
   - **На `connection.closed`**:
     - Проверить защиту от гонки (race condition): сбрасывать `last_checked_result = False` только если закрывающееся соединение совпадает с текущим активным или новее его.
     - Установить `last_checked_result = False`.
     - Обновить `last_checked_at = datetime.utcnow()`.
     - Поля `app_connect` и `svc_connect` **не изменять** (сохраняются для восстановления при реконнекте).
   - **На сообщения presence из топиков MQTT (`dev/{SN}/app` и `dev/{SN}/svc`)**:
     - При получении `app_online` -> `app_connect = True`.
     - При получении `app_offline` (LWT падения процесса) -> `app_connect = False`.
     - При получении `svc_online` -> `svc_connect = True`.
     - При получении `svc_offline` (LWT падения процесса) -> `svc_connect = False`.

4. **Транзакционность и надежность**:
   - Подтверждение сообщения (`basic_ack`) производить строго после успешного коммита транзакции в БД.
   - Автоматический реконнект консьюмера с экспоненциальной задержкой при сбоях брокера.

---

#### 4. Блок Backend: Рефакторинг таймера-поллера Management API

1. **Изменение периодичности и режима поллинга**:
   - Перевести периодический запуск сбора `details` на **10 минут** (или сделать настраиваемым через `.env`: `DEVICE_POLL_INTERVAL_SEC=600`).
2. **Мягкий сбор деталей (Batch / Chunking)**:
   - При сборе данных с `GET /api/connections` выполнять постраничную обработку либо порционную обработку списка терминалов (chunks по 50-100 устройств) без блокировки event loop.
   - Обновлять расширенную статистику: `ip_address`, `port`, `ssl_cipher`, `connected_at`, `bytes_received`, `bytes_sent`.
3. **Сверка (Reconciliation)**:
   - Если в Management API устройство активно, а в БД `last_checked_result = False` (или наоборот), скорректировать статус до актуального.
4. **Холодный старт**:
   - При старте сервиса выполнить однократный initial sync для мгновенного заполнения таблицы подключений.

---

#### 5. План тестирования и приемки
1. **Тест подключения**: Запустить эмулятор терминала / `leo4proxy` -> убедиться, что через `amq.rabbitmq.event` событие `connection.created` пришло за <100мс и выставило `last_checked_result = True`.
2. **Тест аварийного отключения (LWT сети)**: Принудительно убить TCP-сокет клиента -> убедиться, что `connection.closed` перевел `last_checked_result = False`, при этом `app_connect` и `svc_connect` сохранили прежние значения.
3. **Тест реконнекта**: Восстановить подключение -> `last_checked_result` переходит в `True`, приложения сразу доступны в API без повторной отправки presence.
4. **Тест LWT локального процесса**: Прибить только процесс `extra_service` -> убедиться, что через топик `dev/{SN}/svc` флаг `svc_connect` перешел в `False` при `last_checked_result = True`.
5. **Тест бэкапа и восстановления**: Проверить успешный экспорт `definitions_backup.json` и целостность очередей после включения плагина.
```

---

### Резюме
Промпт полностью готов к использованию в проекте `D:\work\iot.leo4.ru\iot-rpc-rest-app`. Он учитывает все технические нюансы, предотвращает гонки состояний и гарантирует сохранность данных RabbitMQ при деплое.