[![Build and push images to GHCR](https://github.com/OlegLebedevRU/iot-rpc-rest-app/actions/workflows/build-and-push.yaml/badge.svg)](https://github.com/OlegLebedevRU/iot-rpc-rest-app/actions/workflows/build-and-push.yaml)
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
| 🦾 **Robotics-ready** | Полный стек для роботов: OTA (ESP32 + STM32), NFC / HMI / реле, SIP-голос, RTP-видео, AI-native MCP, физическое подтверждение действий |
| 🏭 **Serial Production** | Автоматизированный конвейер серийного производства: bulk-выпуск сертификатов, прошивка, регистрация и онбординг устройств |
| 🔏 **Stand-alone CA / Auth** | Автономные (offline/air-gapped) центры сертификации и авторизации — полный контроль PKI без зависимости от внешних сервисов |

---

## 📚 Документация

### Протоколы и API

| Документ | Описание |
|---|---|
| 📡 [**RPC-протокол (MQTT v5)**](./docs/mqtt-rpc-protocol.md) | Асинхронный RPC поверх MQTT 5: топики, correlation data, Polling & Trigger |
| 🔢 [**Справочник method_code**](./docs/method-codes-reference.md) | Единый источник истины по `method_code`, совместимости `Platerra` / `Siplite` / `l4-hmi`, форматам `payload.dt` и ответам `res` |
| 📋 [**REST API: задачи (task workflow)**](./docs/1-task-workflow-doc.md) | HTTP-интерфейс управления задачами: touch_task, статусы, вебхуки |
| 📨 [**API событий устройств (events)**](./docs/2-events-api-format-description.md) | Получение асинхронных событий и телеметрии через REST |
| 🔔 [**Webhooks**](./docs/3-webhooks.md) | Push-уведомления о результатах задач и событиях |

### Диаграммы и сценарии

| Документ | Описание |
|---|---|
| 🔀 [**Sequence диаграммы**](./docs/sequence.md) | End-to-end сценарии: touch_task → MQTT RPC → result |
| 🗂️ [**Состояния задачи**](./docs/task_states.md) | State machine задачи: READY → PENDING → LOCK → DONE/FAILED |
| 📊 [**Граф клиентского потока RPC**](./docs/mqtt-rpc-client-flow.md) | Mermaid-диаграммы: Polling, Trigger, Fail-fast |
| 🧬 [**Матрица correlation data**](./docs/mqtt-rpc-correlation-matrix.md) | Где и как передаётся `correlationData` в `tsk` / `req` / `rsp` / `res` / `cmt` |

### Интеграция

| Документ | Описание |
|---|---|
| 🤖 [**AI-агент: руководство**](./docs/ai-agent-integration-guide.md) | Подключение LLM, MCP-сервера или чат-бота к Leo4 API |
| 🖥️ [**Серверная интеграция**](./docs/server-integration-guide.md) | Руководство по интеграции серверной стороны с IoT RPC |
| 🟠 [**Серверная интеграция: Kotlin + Spring Boot**](./docs/server-integration-guide-kotlin-spring.md) | Пример интеграции на Kotlin + Spring Boot |
| 🤖 [**Robotics**](./robotics/marketing-overview.md) | LEO4 Robotics Platform: управление автономными устройствами и роботами |

### Обзор платформы

| Документ | Описание |
|---|---|
| 🎯 [**Презентация решения**](./docs/solution-presentation.md) | Полный обзор платформы: концепция, архитектура, сценарии |
| ⏱️ [**TTL**](./docs/TTL.md) | Правила декремента TTL, поллинг и поведение при TTL=0 |
| 🏷️ [**Типы событий**](./docs/event-types-reference.md) | Реестр `event_type_code`, включая `L4HmiEvent` для результата обновления UI-каталога |
| 🏷️ [**Теги событий**](./docs/event-property-tags.md) | Справочник числовых тегов payload событий устройств |

> ℹ️ Для RPC-интеграций начните со связки: [`mqtt-rpc-protocol.md`](./docs/mqtt-rpc-protocol.md) → [`method-codes-reference.md`](./docs/method-codes-reference.md) → [`mqtt-rpc-client-flow.md`](./docs/mqtt-rpc-client-flow.md).
> 🆕 Для кейса `l4-hmi` + `method_code=17` (`UI-Catalog`) смотрите также [`event-types-reference.md`](./docs/event-types-reference.md) и [`event-property-tags.md`](./docs/event-property-tags.md).

---

## 💻 Примеры и симуляторы

> Все примеры используют двустороннюю SSL-аутентификацию (mutual TLS)

### 🐍 Python
- [`mqtt5-paho-full-rpc-client-example.py`](./examples/mqtt5-paho-full-rpc-client-example.py) — полный RPC-клиент на paho-mqtt
- [`mini-native-paho-mqttv5-corrdata-client.py`](./examples/mini-native-paho-mqttv5-corrdata-client.py) — минимальный пример с correlation data
- [`rpc-client-example.py`](./examples/rpc-client-example.py) — базовый пример клиента

### 🐍 Device emulator (python)
- [`device-emulator/`](./device-emulator/) — Device emulator (mock RPC method 51 + healthcheck/test events)

### 🔷 C# / .NET
- [`rpc-client-example.cs`](./examples/rpc-client-example.cs) — RPC-клиент на .NET
- [`rpc-client-native-correlation-example.cs`](./examples/rpc-client-native-correlation-example.cs) — native correlation data
- [`rpc-client-extract-SN-from-cert-example.cs`](./examples/rpc-client-extract-SN-from-cert-example.cs) — извлечение SN из сертификата

### ⚙️ C / Windows
- [`c-win-clion-rpc-client/`](./examples/c-win-clion-rpc-client/) — RPC-клиент для Windows

### ⚙️ C / FreeRTOS
- Siplite — RPC-клиент + SIP + WebRTC для ESP32/STM32 (по запросу)

### 🎮 Сценарии устройств

| Платформа | Сценарий |
|---|---|
| 🖥️ Windows / Linux | Удалённая отправка файла в Telegram, запись экрана (ffmpeg), запуск произвольных команд |
| 🐍 Python Agent | Удалённый запуск fullscreen-формы (tkinter), выполнение произвольного кода, WebRTC-стриминг с Raspberry Pi |
| 📟 ESP32 (ESP-IDF) | PWM-управление LED, RS-485, SIP-звонок (ESP-ADF), управление постаматом |
| 🔬 STM32 | Удалённый запуск измерений с кастомными параметрами, передача массива данных |

---

## 📊 Diagrams (some use cases)

### 🔬 STM32 | Cloud Bootloader

> Обновление прошивки STM32 через облако: ESP32 выступает хостом и передаёт прошивку на STM32 по шине I2C / UART / SPI.

```mermaid
sequenceDiagram
    participant Cloud as ☁️ Leo4 Cloud
    participant ESP32 as 📟 ESP32 Host
    participant STM32 as 🔬 STM32

    Cloud->>ESP32: RPC: flash_firmware(fw_chunk[]) via MQTTS
    activate ESP32
    ESP32->>ESP32: Validate & buffer firmware
    loop I2C / UART / SPI transfer
        ESP32->>STM32: Bootloader protocol: send chunk
        STM32-->>ESP32: ACK / NACK
    end
    ESP32->>STM32: Boot command (reset to app)
    STM32-->>ESP32: Boot OK
    deactivate ESP32
    ESP32->>Cloud: RPC result: flash_ok / flash_error
```

---

### 🔊 TTS Voice-Terminal | Chat → Cloud AI → TTS.MP3 → Player

> Голосовой терминал: текстовый чат отправляется в облачный AI, ответ синтезируется в MP3 и воспроизводится на устройстве через Leo4 RPC-сигнализацию.

```mermaid
sequenceDiagram
    participant User  as 💬 Chat / App
    participant Leo4  as ☁️ Leo4 API
    participant AI    as 🤖 Cloud AI (LLM)
    participant TTS   as 🔉 TTS Service
    participant Dev   as 🔊 Player Device

    User->>Leo4: POST /task  { method: tts_speak, text: "..." }
    Leo4->>AI: Chat completion request
    AI-->>Leo4: AI response text
    Leo4->>TTS: Synthesize speech → MP3
    TTS-->>Leo4: audio.mp3 (URL / bytes)
    Leo4->>Dev: RPC via MQTT: play_audio(url)
    Dev-->>Leo4: RPC result: playback_done
    Leo4-->>User: Webhook / poll result
```

---

### 🤖 AI | Bulk Telemetry → Decision → Escalation → Group Task / OTA

> AI массово принимает через Leo4 IoT Platform временные ряды данных и онлайн-показатели от периферии, обрабатывает их, принимает решение и эскалирует важное на ответственного, затем формирует групповое задание (включая новую прошивку MCU) и отправляет его на сегменты устройств.

```mermaid
sequenceDiagram
    participant Devs  as 📡 IoT Devices<br/>(periphery segment)
    participant Leo4  as ☁️ Leo4 IoT Platform
    participant AI    as 🤖 AI Agent
    participant Resp  as 👤 Responsible<br/>(operator / manager)

    Note over Devs,Leo4: Continuous telemetry stream
    loop Time-series & online metrics
        Devs->>Leo4: MQTT event: sensor_data {ts, values[]}
        Leo4-->>AI: Webhook / poll: telemetry batch
    end

    Note over AI: Analyse time-series,<br/>detect anomalies / thresholds
    AI->>AI: Process & decide

    alt Critical anomaly detected
        AI->>Resp: Escalation alert<br/>(email / push / messenger)
        Resp-->>AI: Acknowledge / approve action
    end

    Note over AI,Leo4: Form group task for device segment
    AI->>Leo4: POST /task {method: group_command OR flash_firmware,<br/>targets: [segment_id], payload: {fw_chunk[] / params}}
    Leo4->>Devs: RPC via MQTTS: execute task<br/>(group_command / flash_firmware)
    activate Devs
    Devs->>Devs: Execute command or apply OTA firmware
    Devs-->>Leo4: RPC result: ok / error
    deactivate Devs
    Leo4-->>AI: Webhook: task results summary
    AI->>Resp: Final report (success / failures)
```

---

## 🏭 Сценарий и автоматизация серийного производства

> Платформа поддерживает полный цикл серийного выпуска IoT-устройств: от генерации сертификатов и прошивки на конвейере до автоматической регистрации и онбординга в облаке.

```mermaid
sequenceDiagram
    participant Factory  as 🏭 Производственная линия
    participant CA       as 🔏 Stand-alone CA<br/>(offline / air-gapped)
    participant Auth     as 🔐 Stand-alone<br/>Auth Center
    participant Flasher  as ⚡ Прошивальщик
    participant Device   as 📟 Устройство
    participant Cloud    as ☁️ Leo4 Cloud

    Note over Factory,CA: Подготовка пакета сертификатов (bulk)
    Factory->>CA: Запрос на выпуск N сертификатов (device_id, SN)
    CA-->>Factory: device.crt + device.key (x509, уникальный SN)

    Note over Factory,Flasher: Прошивка и персонализация
    Factory->>Flasher: Прошивка + сертификат + конфиг (Wi-Fi, broker URL)
    Flasher->>Device: Flash: firmware + PKI bundle + config
    Device-->>Flasher: Flash OK

    Note over Device,Auth: Первый запуск — автоматический онбординг
    Device->>Auth: mTLS-запрос: предъявление device.crt
    Auth-->>Device: JWT-токен доступа (ограниченные права, onboarding scope)

    Device->>Cloud: POST /register  { sn, fw_version, hw_rev } + JWT
    Cloud-->>Device: 200 OK — устройство зарегистрировано, получены ACL-правила

    Note over Device,Cloud: Штатная работа
    Device->>Cloud: MQTTS (mTLS): подключение к брокеру, публикация телеметрии
    Cloud-->>Device: RPC-команды, OTA-обновления
```

---

## 🔐 Безопасность

### Транспортная и прикладная защита

- **mutual TLS (mTLS)** — двусторонняя аутентификация: сервер и каждое устройство предъявляют сертификаты
- **PKI (x509)** — сквозная адресация устройств; серийный номер устройства = CN сертификата
- **JWT (RSA)** — авторизация API-клиентов и серверных приложений
- **RabbitMQ ACL** — строгие политики маршрутизации на уровне MQTT-брокера (топики per-device)
- **nginx** — TLS-терминация, JWT-валидация, rate limiting, IP-фильтрация

### 🔏 Автономные центры сертификации и авторизации (Stand-alone CA / Auth)

Leo4 поддерживает развёртывание полностью автономной PKI-инфраструктуры без зависимости от публичных удостоверяющих центров или облачных сервисов:

| Компонент | Описание |
|---|---|
| **Root CA (offline)** | Корневой УЦ хранится в изолированной (air-gapped) среде; используется только для подписания Intermediate CA |
| **Intermediate CA** | Оперативный УЦ для выпуска сертификатов устройств и серверов; может работать в закрытом сегменте производственной сети |
| **Device CA** | Выделенный УЦ для массового выпуска клиентских сертификатов на конвейере (bulk provisioning) |
| **Stand-alone Auth Center** | Сервис авторизации (JWT / OAuth2) без внешних зависимостей; поддерживает scoped-токены для onboarding, телеметрии и управления |
| **CRL / OCSP (опционально)** | Списки отзыва сертификатов и OCSP-ответчик для своевременного отзыва скомпрометированных устройств |

> Такая архитектура позволяет развернуть платформу в закрытых сетях (промышленные объекты, военная и медицинская техника, критическая инфраструктура) с полным контролем над цепочкой доверия.

---

## 🛠️ Технологический стек

`Python 3` · `FastAPI` · `FastStream` · `PostgreSQL` · `RabbitMQ + MQTT 5` · `nginx` · `Docker Compose` · `PKI (x509)`

---

## 🎛️ Контроллеры

`STM32` · `ESP32` · `C` · `FreeRTOS` · `ESP-IDF` · `ESP-ADF`

---

> 📧 info@platerra.ru · 🌐 https://platerra.ru · © 2026 Leo4
