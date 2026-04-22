# 🌐 Leo4 IoT Platform

> Транспортный фреймворк для создания защищённых систем управления и телеметрии распределённой сети кроссплатформенных IoT-устройств.

```
[ЛК / App / AI-агент] ←→ [REST API + Core] ←→ [Рой устройств]
```

---

## 🏗️ Архитектура

```mermaid
flowchart LR
    subgraph Client["Клиент"]
        App["App / AI-агент"]
    end

    subgraph Core["Leo4 Cloud Core"]
        API["REST API\n+ Webhooks"]
        Engine["RPC Engine\n+ Task Queue"]
        Broker["MQTT 5\nBroker"]
        API --- Engine --- Broker
    end

    subgraph Devices["IoT-устройства"]
        D1["FreeRTOS\nESP32 / STM32"]
        D2["Python / C# Agent\nWindows / Linux / RPi"]
        D3["Custom MQTT 5\nDevice"]
    end

    App -->|"HTTP\ntask / events"| API
    API -->|"Webhook\nresults / events"| App
    Broker <-->|MQTTS mTLS| D1
    Broker <-->|MQTTS mTLS| D2
    Broker <-->|MQTTS mTLS| D3
```

---

## ✨ Ключевые принципы

| | |
|---|---|
| 🔗 **Loose Coupling** | Событийная модель, слабосвязанные устройства |
| 🔑 **PKI / x509** | Сквозная адресация устройств через сертификаты |
| ⚡ **Async RPC** | Очередь задач с приоритетами и TTL |
| 🔄 **Push + Pull** | Двойная стратегия доставки для нестабильных сетей |
| 🛡️ **Security** | mutual TLS, JWT (RSA), API-ключи, ACL брокера |
| 🤖 **AI-ready** | REST + Webhooks совместимы с Function Calling / MCP |

---

## 📚 Документация

### Протоколы и API

| Документ | Описание |
|---|---|
| 📡 [**RPC-протокол (MQTT v5)**](./docs/mqtt-rpc-protocol.md) | Асинхронный RPC поверх MQTT 5: топики, correlation data, Polling & Trigger |
| 📋 [**REST API: задачи (task workflow)**](./docs/1-task-workflow-doc.md) | HTTP-интерфейс управления задачами: touch_task, статусы, вебхуки |
| 📨 [**API событий устройств (events)**](./docs/2-events-api-format-description.md) | Получение асинхронных событий и телеметрии через REST |
| 🔔 [**Webhooks**](./docs/3-webhooks.md) | Push-уведомления о результатах задач и событиях |

### Диаграммы и сценарии

| Документ | Описание |
|---|---|
| 🔀 [**Sequence диаграммы**](./docs/sequence.md) | End-to-end сценарии: touch_task → MQTT RPC → result |
| 🗂️ [**Состояния задачи**](./docs/task_states.md) | State machine задачи: READY → PENDING → LOCK → DONE/FAILED |
| 📊 [**Граф клиентского потока RPC**](./docs/mqtt-rpc-client-flow.md) | Mermaid-диаграммы: Polling, Trigger, Fail-fast |

### Интеграция

| Документ | Описание |
|---|---|
| 🤖 [**AI-агент: руководство**](./docs/ai-agent-integration-guide.md) | Подключение LLM, MCP-сервера или чат-бота к Leo4 API |
| 🖥️ [**Серверная интеграция**](./docs/server-integration-guide.md) | Руководство по интеграции серверной стороны с IoT RPC |
| 🏗️ [**App Stack**](./docs/app_stack.md) | Стек технологий: FastAPI, RabbitMQ, PostgreSQL, nginx, PKI |

### Обзор платформы

| Документ | Описание |
|---|---|
| 🎯 [**Презентация решения**](./docs/solution-presentation.md) | Полный обзор платформы: концепция, архитектура, сценарии |
| ⏱️ [**TTL**](./docs/TTL.md) | Правила декремента TTL, поллинг и поведение при TTL=0 |
| 🔢 [**Справочник method_code**](./docs/method-codes-reference.md) | Реестр команд: диапазоны, форматы payload, ответы |
| 🏷️ [**Теги событий**](./docs/event-property-tags.md) | Справочник числовых тегов payload событий устройств |

---

## 💻 Примеры и симуляторы

> Все примеры используют двустороннюю SSL-аутентификацию (mutual TLS)

### 🐍 Python
- [`mqtt5-paho-full-rpc-client-example.py`](./examples/mqtt5-paho-full-rpc-client-example.py) — полный RPC-клиент на paho-mqtt
- [`mini-native-paho-mqttv5-corrdata-client.py`](./examples/mini-native-paho-mqttv5-corrdata-client.py) — минимальный пример с correlation data
- [`rpc-client-example.py`](./examples/rpc-client-example.py) — базовый пример клиента

### 🔷 C# / .NET
- [`rpc-client-example.cs`](./examples/rpc-client-example.cs) — RPC-клиент на .NET
- [`rpc-client-native-correlation-example.cs`](./examples/rpc-client-native-correlation-example.cs) — native correlation data
- [`rpc-client-extract-SN-from-cert-example.cs`](./examples/rpc-client-extract-SN-from-cert-example.cs) — извлечение SN из сертификата

### ⚙️ C / FreeRTOS
- [`c-win-clion-rpc-client/`](./examples/c-win-clion-rpc-client/) — RPC-клиент для ESP32 / STM32

### 🎮 Сценарии устройств
## Diagrams

| Платформа | Сценарий |
|---|---|
| 🖥️ Windows / Linux | Удалённая отправка файла в Telegram, запись экрана (ffmpeg), запуск произвольных команд |
| 🐍 Python Agent | Удалённый запуск fullscreen-формы (tkinter), выполнение произвольного кода, WebRTC-стриминг с Raspberry Pi |
| 📟 ESP32 (ESP-IDF) | PWM-управление LED, RS-485, SIP-звонок (ESP-ADF), управление постаматом |
| 🔬 STM32 | Удалённый запуск измерений с кастомными параметрами, передача массива данных |

---

## 🔐 Безопасность

- **mutual TLS** — аутентификация устройств по клиентским сертификатам
- **PKI (x509)** — CA на базе openssl / pyca/cryptography
- **JWT (RSA)** — авторизация API-клиентов
- **RabbitMQ ACL** — строгие политики маршрутизации на уровне брокера
- **nginx** — TLS-терминация, rate limiting

---

## 🛠️ Технологический стек

`Python 3` · `FastAPI` · `FastStream` · `PostgreSQL` · `RabbitMQ + MQTT 5` · `nginx` · `Docker Compose` · `PKI (x509)`

---

> 📧 info@platerra.ru · 🌐 https://platerra.ru · © 2026 Leo4
