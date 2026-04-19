# Техническое исследование: LEO4 как робототехническая платформа

> **Версия:** 1.0  
> **Дата:** 2026-04-19  
> **Автор:** AI-исследование по запросу OlegLebedevRU  
> **Репозитории:** iot-rpc-rest-app · sip_periph · siplite · siplite_pcb

---

## Содержание

1. [Методология и источники](#1-методология-и-источники)
2. [Полный стек компонентов](#2-полный-стек-компонентов)
3. [Архитектура платформы](#3-архитектура-платформы)
4. [Аппаратный узел: sip_periph + siplite_pcb](#4-аппаратный-узел-sip_periph--siplite_pcb)
5. [Коммуникационный шлюз: siplite (ESP32)](#5-коммуникационный-шлюз-siplite-esp32)
6. [Облачный слой: iot-rpc-rest-app](#6-облачный-слой-iot-rpc-rest-app)
7. [AI/MCP-слой](#7-aimcp-слой)
8. [I2C-контракт: ESP32 ↔ STM32](#8-i2c-контракт-esp32--stm32)
9. [Сценарии использования в робототехнике](#9-сценарии-использования-в-робототехнике)
10. [Ограничения и предпосылки внедрения](#10-ограничения-и-предпосылки-внедрения)
11. [Выводы и синтез](#11-выводы-и-синтез)

---

## 1. Методология и источники

### Что подтверждено репозиториями напрямую

Исследование основано на следующих источниках:

| Репозиторий | Статус | Изученные файлы |
|-------------|--------|-----------------|
| `OlegLebedevRU/iot-rpc-rest-app` | ✅ Публичный | `README.md`, `compose.yaml`, `docs/`, `mcp/README.md`, `mcp/leo4_mcp/` |
| `OlegLebedevRU/sip_periph` | ✅ Публичный | `README.md`, `CHECKLIST.md`, `Core/Inc/`, `docs/i2c_global_contract.md`, `docs/tca6408_integration.md` |
| `OlegLebedevRU/siplite` | ✅ Публичный | `README.md`, `AGENTS.md`, `docs/ota.md`, `docs/stm32_bin_download.md`, `docs/stm32_hw.md`, `docs/solution-presentation.md`, `main/*`, `components/*`, `partitions_sip_1.csv` |
| `OlegLebedevRU/siplite_pcb` | ⛔ Приватный / недоступен | — |

> **Обозначения в тексте:**  
> ✅ **[подтверждено]** — факт прямо следует из кода или документации  
> 🔷 **[вывод]** — аккуратный вывод по совокупности доступных материалов  
> ⚪ **[предположение]** — гипотеза, требующая подтверждения

---

## 2. Полный стек компонентов

```mermaid
graph TB
    subgraph Cloud["Облачный слой"]
        API["LEO4 REST API\n(FastAPI / Python)"]
        DB[(PostgreSQL)]
        MQ["RabbitMQ\n+ MQTT Plugin"]
        GW["nginx\n(JWT + Mutual TLS)"]
        MCP["MCP-сервер\nleo4_mcp"]
    end

    subgraph Gateway["Шлюз устройства (ESP32)"]
        MQTT_C["MQTT-клиент\n(MQTT 5.0)"]
        SIP["SIPLite\n(VoIP стек)"]
        I2C_M["I2C Master\n(400 kHz)"]
        ETH["KSZ8863\nEthernet Switch\n(2 порта)"]
        RTP["l4_rtp_bridge\n(RTP bridge)"]
        OTA_ESP["leo4_ota\n(OTA ESP32)"]
        STM_FW["l4_stm32_fw\n(OTA STM32)"]
    end

    subgraph Periph["Периферийный контроллер (STM32F411CEU)"]
        RTOS["FreeRTOS\n(многозадачность)"]
        NFC["PN532\n(NFC/RFID)"]
        RELAY["Relay\nActuator"]
        OLED["SSD1306\n(OLED)"]
        DWIN["DWIN Display\n(UART HMI)"]
        KBD["Matrix\nKeyboard"]
        TCA["TCA6408A\n(GPIO Expander)"]
        RTC["DS3231\n(RTC)"]
        WIEG["Wiegand\nReader"]
        USB["USB CDC\n(диагностика)"]
        RS485["RS-485\n(промышл. шина)"]
        SPIDISP["SPI OLED/TFT\n(дисплей)"]
    end

    subgraph AI["AI/Агент"]
        LLM["Claude / Cursor /\nVS Code Copilot"]
    end

    LLM <-->|"MCP stdio/SSE"| MCP
    MCP <-->|"HTTPS + x-api-key"| API
    API --- DB
    API <-->|"AMQP"| MQ
    MQ <-->|"MQTT 5.0 / TLS"| MQTT_C
    GW --> API
    MQTT_C --- SIP
    MQTT_C --- I2C_M
    MQTT_C --- RTP
    ETH --- MQTT_C
    OTA_ESP --- MQTT_C
    STM_FW --- I2C_M
    I2C_M <-->|"I2C 400kHz\naddr 0x11"| RTOS
    RTOS --- NFC
    RTOS --- RELAY
    RTOS --- OLED
    RTOS --- DWIN
    RTOS --- KBD
    RTOS --- TCA
    RTOS --- RTC
    RTOS --- WIEG
    RTOS --- USB
    RTOS --- RS485
    RTOS --- SPIDISP
```

---

## 3. Архитектура платформы

### 3.1 Уровни стека ✅ [подтверждено]

Платформа состоит из четырёх уровней:

| Уровень | Репозиторий | Технологии |
|---------|-------------|------------|
| **AI/Agent** | iot-rpc-rest-app / `mcp/` | MCP (Model Context Protocol), Python, stdio/SSE |
| **Cloud API** | iot-rpc-rest-app / `app-service/` | FastAPI, FastStream, PostgreSQL, RabbitMQ, MQTT 5.0, nginx, JWT (RSA), x509 |
| **Gateway** | siplite | ESP32, FreeRTOS, MQTT5, SIPLite, I2C Master, KSZ8863 Ethernet Switch, RTP bridge, OTA |
| **Hardware** | sip_periph + siplite_pcb | STM32F411CEU, FreeRTOS, PN532, SSD1306, DWIN, TCA6408A, DS3231, реле, USB CDC, RS-485, SPI дисплей |

### 3.2 Ключевые принципы архитектуры ✅ [подтверждено]

Из `README.md` iot-rpc-rest-app:

- **Loose coupling** — каждое устройство имеет уникальный адрес на базе x509
- **Async queued paradigm** — команды ставятся в очередь с TTL и приоритетами
- **"Last mile protocol"** — MQTT 5.0 для связи облака с устройством
- **Two-way SSL authentication** — обязательная взаимная TLS-аутентификация
- **Request/response + polling** — гибридная модель подтверждения выполнения

---

## 4. Аппаратный узел: sip_periph + siplite_pcb

### 4.1 Микроконтроллер ✅ [подтверждено]

**Файл:** `sip_periph/README.md`, `sip_periph/sip_periph.ioc`, `sip_periph/STM32F411CEUX_FLASH.ld`

- MCU: **STM32F411CEU** (ARM Cortex-M4 @ 100 MHz, 512 KB Flash, 128 KB RAM)
- IDE: STM32CubeIDE / STM32CubeMX (HAL)
- RTOS: **FreeRTOS** (конфигурация в `Core/Inc/FreeRTOSConfig.h`)
- Компиляция: Makefile + GCC ARM, целевые файлы `.elf`/`.bin`

### 4.2 Периферия ✅ [подтверждено]

Из заголовочных файлов `Core/Inc/`:

| Компонент | Заголовок | Назначение |
|-----------|-----------|------------|
| PN532 | `pn532_com.h`, `service_pn532_task.h` | NFC/RFID считыватель |
| SSD1306 | `ssd1306.h`, `ssd1306_conf.h` | OLED-дисплей I2C |
| DWIN | `app_uart_dwin.h`, `app_uart_dwin_tx.h`, `dwin_gfx.h` | HMI-дисплей UART с тачскрином |
| TCA6408A | `tca6408a_map.h`, `service_tca6408.h` | I2C GPIO-расширитель (8 пинов) |
| DS3231 | `service_time_sync.h` | Прецизионный RTC с 1Hz прерыванием |
| Matrix KBD | `service_matrix_kbd.h` | Матричная клавиатура |
| Relay | `service_relay_actuator.h` | Релейный актуатор |
| Wiegand | (в пакете PACKET_WIEGAND) | Считыватель доступа Wiegand |
| USB CDC | (USB Device) | USB CDC для диагностики и локального взаимодействия |
| RS-485 | `app_uart_rs485.h` | RS-485 шина для замковых плат и промышленного оборудования |
| SPI Display | (SPI интерфейс) | OLED/TFT дисплеи на SPI (помимо DWIN UART HMI) |
| TCA6408A GPIO | `tca6408a_map.h`, `service_tca6408.h` | Дополнительные GPIO свободного назначения через GPIO expander |

> ✅ **[подтверждено]** USB Device (USB CDC) и RS-485 подтверждены `docs/solution-presentation.md` из репозитория `siplite`. GPIO расширение через TCA6408A — прямые выводы STM32 и TCA6408A.

### 4.3 Программные службы FreeRTOS ✅ [подтверждено]

Из `docs/tca6408_integration.md` и `CHECKLIST.md`:

- `StartTasktca6408a` — обработка прерываний GPIO-расширителя
- `StartTaskRxTxI2c1` — I2C обмен с ESP32 (мастер)
- `service_tca6408_process_irq_event()` — диспетчер событий (DS/кнопка/PN532)
- `HAL_GPIO_EXTI_Callback()` — роутер прерываний → FreeRTOS очереди

### 4.4 Поток данных: DS3231 → ESP32 ✅ [подтверждено]

Из `CHECKLIST.md` и `docs/i2c_global_contract.md`:

```mermaid
sequenceDiagram
    participant DS3231
    participant TCA6408A
    participant STM32
    participant ESP32

    DS3231->>TCA6408A: 1Hz импульс (INT/SQW → p0)
    TCA6408A->>STM32: EXTI прерывание (GPIO_PIN_13, GPIOC)
    STM32->>STM32: HAL_GPIO_EXTI_Callback()
    STM32->>STM32: xQueueSendFromISR(myQueueTCA6408Handle)
    STM32->>STM32: StartTasktca6408a читает DS3231
    STM32->>STM32: PACKET_TIME в myQueueToMasterHandle
    ESP32->>STM32: I2C read reg=0x00 len=1 (тип пакета)
    ESP32->>STM32: I2C read reg=0x80 len=8 (время BCD)
    ESP32->>ESP32: Синхронизация времени
```

### 4.5 PCB: siplite_pcb 🔷 [вывод]

Репозиторий `siplite_pcb` недоступен публично. По контексту:
- Кастомная PCB, объединяющая STM32F411CEU + ESP32 + периферию
- Форм-фактор: компактный модуль для встраивания в устройства (постаматы, локеры)
- Установлен чип Ethernet switch **KSZ8863** (см. раздел 5.4)
- Вероятно содержит: KiCad/EasyEDA файлы, схемы, Gerber-файлы

---

## 5. Коммуникационный шлюз: siplite (ESP32)

### 5.1 Архитектура приложения ESP32 ✅ [подтверждено]

**Источники:** `docs/solution-presentation.md`, `AGENTS.md` из репозитория `siplite`

**Цепочка запуска:**

```
app_main() → l4_app_bootstrap() → l4_app_start_services() → l4_app_run_main_loop()
```

**Bootstrap** (`l4_app_bootstrap.c`):
- Инициализация NVS / сертификатов / хранилища
- Подъём Ethernet (KSZ8863 — двухпортовый switch)
- Инициализация frontend, AV stream
- Сброс и запуск шины STM32
- Запуск менеджера SIP-регистрации

**Runtime** (`l4_app_runtime.c`):
- HTTP/WS сервер (`/gate`, `/event`, `/task`, `/nvs`)
- Gateway transport callbacks
- MQTT5 клиент
- Task payload parser
- SN broadcast (mDNS)

### 5.2 Модули ESP32 ✅ [подтверждено]

**Источник:** `main/` репозитория `siplite`

| Модуль | Размер | Назначение |
|--------|--------|------------|
| `l4_app_bootstrap.c` | — | Инициализация всей системы |
| `l4_app_runtime.c` | — | Запуск сервисов (HTTP, MQTT, задачи) |
| `l4_sip_reg_manager.c` | — | SIP lifecycle (event-driven: IP_EVENT_ETH_GOT_IP / LOST_IP) |
| `l4_i2c_master.c` | 39 KB | I2C Master (основная шина I2C_NUM_1, 400 kHz) |
| `l4_input_processing.c` | — | Обработка NFC/PIN |
| `l4_task_payload_parcer.c` | — | Разбор MQTT RPC команд |
| `leo4_nvs_handler.c` | — | Унифицированный NVS handler |
| `leo4_web.c` | — | HTTP/WS сервер (/gate, /event, /task, /nvs) |
| `l4_event_router.c` | — | Маршрутизация событий |
| `l4_rtp_bridge.c` | 12.5 KB | RTP bridge для видеопотоков |
| `l4_stm32_fw.c` | 49 KB | Прошивка STM32 через I2C bootloader |
| `l4_stm32_bin_download.c` | — | Загрузка бинарника STM32 по HTTPS |
| `leo4_ota.c` | — | OTA обновление ESP32 |
| `leo4_eth_two_ports.c` | 22 KB | Ethernet два порта (KSZ8863 switch) |
| `l4_shutdown.c` | — | Graceful shutdown |
| `l4_healthcheck.c` | — | Healthcheck |
| `l4_mdns.c` | — | mDNS |
| `leo4_stm32_bus.c` | — | STM32 I2C bus communication |

### 5.3 Компоненты ESP32 ✅ [подтверждено]

**Источник:** `components/` репозитория `siplite`

| Компонент | Назначение |
|-----------|------------|
| `l4_sip` | SIP стек |
| `l4_mqtt5` | MQTT 5 клиент |
| `l4_gateway_transport` | Gateway transport |
| `l4_cloud_codec` | Cloud codec |
| `l4_types` | Базовые типы |
| `audio_board`, `audio_hal`, `audio_stream` | Аудио стек (ESP-ADF) |
| `audio_flash_tone`, `av_stream` | Аудио/видео streaming |
| `ca_certs` | Корневые сертификаты |
| `tone_partition` | Тональные сигналы |

### 5.4 Partition table ✅ [подтверждено]

**Источник:** `partitions_sip_1.csv` репозитория `siplite`

| Раздел | Размер | Описание |
|--------|--------|----------|
| `esp_secure_cert` | 0x5000 | Зашифрован — сертификат устройства |
| `nvs` | 0x3000 | Основной NVS |
| `otadata` | 0x2000 | OTA метаданные (зашифрован) |
| `nvs_key` | 0x1000 | Ключи NVS (зашифрован) |
| `fctry` | 0x18000 | Factory NVS |
| `cfg` | 0x2C000 | Configuration NVS (`cfg_eth/eth_port_mode` и др.) |
| `stm32_bin` | 0x80000 (512 KB) | Хранение прошивки STM32 |
| `db1` | 0xC7000 | Database NVS |
| `log` | 0x6C000 | Логи |
| `flash_tone` | 0x60000 | Звуковые тоны |
| `ota_0` | 0x2B0000 (~2.75 MB) | OTA раздел 0 |
| `ota_1` | 0x2B0000 (~2.75 MB) | OTA раздел 1 |

### 5.5 Ethernet Switch KSZ8863 — два порта ✅ [подтверждено]

**Источник:** `main/leo4_eth_two_ports.c` (22 KB), `simple_switch_main.c` из репозитория `siplite`

На PCB установлен чип Ethernet switch **KSZ8863** с двумя физическими портами:

- **Два Ethernet порта** для подключения к WAN/LAN
- **Режимы работы** настраиваются через NVS: `cfg_eth/eth_port_mode`
- **Проксирование** других Ethernet-устройств (например, IP-камеры)
- **Изоляция IP-трафика**: управление RTP-потоком от IP-камеры на уровне L2

**Ключевой кейс:** IP-камера подключается ко второму порту KSZ8863, трафик изолируется от основной сети. ESP32 выступает шлюзом/proxy для RTSP/RTP потока камеры.

### 5.6 OTA обновление ESP32 ✅ [подтверждено]

**Источник:** `docs/ota.md`, `main/leo4_ota.c` из репозитория `siplite`

| Параметр | Значение |
|----------|---------|
| RPC метод | `SW_UPDATE` (method_code=19) |
| Протокол загрузки | HTTPS (проверка цепочки TLS отключена) |
| OTA разделы | `ota_0` / `ota_1` по ~2.75 MB каждый |
| Уведомление | Асинхронное событие `OTA_RESULT` |
| Защита от параллельного запуска | 409 Conflict |

**Коды результата:** `OTA_OK`, `OTA_ERR_NET`, `OTA_ERR_NO_SPACE`, `OTA_ERR_IMAGE_INVALID`, `OTA_ERR_INTERNAL`

### 5.7 OTA обновление STM32 (периферийного контроллера) ✅ [подтверждено]

**Источник:** `docs/stm32_bin_download.md`, `docs/stm32_hw.md`, `main/l4_stm32_bin_download.c`, `main/l4_stm32_fw.c` из репозитория `siplite`

**Двухэтапный процесс:**

**Этап 1 — Загрузка бинарника (RPC 512 / `STM32_BIN_DOWNLOAD`):**
- Загрузка `.bin` файла по HTTPS
- Сохранение в NVS-раздел `stm32_bin` (512 KB) как blob-чанки (`chunk_0`, `chunk_1`, ...)
- SHA256-верификация после загрузки
- Событие `STM32_BIN_LOAD_RESULT` с кодами `STM32_DL_OK`, `STM32_DL_ERR_*`

**Этап 2 — Прошивка STM32 (RPC 411):**
- Прошивка через I2C bootloader (AN2606 + AN4221)
- I2C адрес bootloader: `0x39`, скорость: 100 kHz
- Протокол команд: `GET`, `GET_VER`, `GET_ID`, `WRITE_MEM_NS`, `EXT_ERASE_NS`, `GO`
- Активация bootloader: BOOT0 + NRST через GPIO expander TCA6408A

> ⚠️ **Ограничение:** периферийный микроконтроллер должен быть подключён в соответствии с паттерном активации bootloader. Для справки по бутлоадерам STM32 есть директория `vendor-docs/` с Application Notes (AN2606, AN4221).

---

## 6. Облачный слой: iot-rpc-rest-app

### 6.1 Сервисный стек ✅ [подтверждено]

Из `compose.yaml`:

| Сервис | Образ/Источник | Порты | Назначение |
|--------|----------------|-------|------------|
| `app1` | `./docker-files/app-service/Dockerfile` | — | FastAPI приложение |
| `rabbitmq` | `rabbitmq:4-management` | 8883, 5672 | MQTT + AMQP брокер |
| `pg` | `postgres` | 5432 | Хранилище задач и событий |
| `pgadmin` | `dpage/pgadmin4` | — | Управление БД |
| `nginx-mutual` | custom | 4443 | Mutual TLS (устройства) |
| `nginx` | custom | 80, 443 | JWT gateway (клиенты) |
| `avahi` | `ydkn/avahi` | host | mDNS для локального depl. |
| `certbot` | `certbot/certbot` | — | Let's Encrypt сертификаты |

### 6.2 Жизненный цикл задачи ✅ [подтверждено]

Из `mcp/README.md`:

```mermaid
stateDiagram-v2
    [*] --> READY: Задача создана
    READY --> PENDING: Устройство приняло
    PENDING --> LOCK: Обрабатывается
    LOCK --> DONE: Доставлено
    READY --> EXPIRED: TTL истёк
    READY --> DELETED: Удалена вручную
    LOCK --> FAILED: Ошибка доставки
    DONE --> [*]
    EXPIRED --> [*]
    DELETED --> [*]
    FAILED --> [*]
```

> **Важно:** `status=3 (DONE)` означает **доставку** команды, а не физическое выполнение. Для подтверждения физического действия используется `poll_device_event`.

### 6.3 Протоколы и безопасность ✅ [подтверждено]

Из `README.md` и `docs/client-cert-ssl-rmq-config.md`:

- Устройства → брокер: **MQTT 5.0** через **Mutual TLS** (порт 8883)
- Клиенты → API: **HTTPS** с **JWT (RSA)**
- Устройство идентифицируется через **x509 сертификат**
- CA управляется через **openssl / pyca/cryptography**

---

## 7. AI/MCP-слой

### 7.1 Компонент leo4_mcp ✅ [подтверждено]

Из `mcp/README.md` и `mcp/leo4_mcp/`:

- **15 MCP-инструментов** (tools) для управления устройствами
- **4 MCP-ресурса** (resources): список устройств, события, коды методов, типы событий
- **3 шаблона промптов** (prompts): открытие ячейки, диагностика, массовая активация
- Поддерживаемые AI-клиенты: Claude Desktop, VS Code (Copilot), Cursor
- Транспорты: **stdio** (по умолчанию), **SSE** (для веб)

### 7.2 Инструменты MCP ✅ [подтверждено]

| Инструмент | Описание |
|------------|----------|
| `open_cell_and_confirm` | Открытие ячейки с подтверждением физического выполнения |
| `poll_device_event` | Опрос событий от устройства |
| `get_telemetry` | Телеметрия (батарея, сигнал, температура) |
| `write_nvs` | Запись конфигурации в NVS устройства |
| `mass_activate` | Параллельная команда для группы устройств |
| `configure_webhook` | Настройка webhook для push-событий |

### 7.3 Интеграция AI с устройствами ✅ [подтверждено]

Из `docs/ai-agent-integration-guide.md` (версия 2.0, 2026-04-04):

```mermaid
sequenceDiagram
    participant User as Пользователь
    participant LLM as AI-ассистент
    participant MCP as leo4_mcp
    participant API as LEO4 REST API
    participant MQTT as RabbitMQ/MQTT
    participant Dev as IoT Устройство

    User->>LLM: "Открой ячейку 7 на устройстве 4619"
    LLM->>MCP: open_cell_and_confirm(device_id=4619, cell=7)
    MCP->>API: POST /device-tasks/ {method_code=51}
    API->>MQTT: AMQP publish
    MQTT->>Dev: MQTT 5.0 deliver
    Dev->>MQTT: Event: CellOpenEvent tag=304
    MQTT->>API: Event received
    MCP->>API: GET /device-events/fields/ (poll)
    MCP->>LLM: confirmed=True
    LLM->>User: "Ячейка 7 открыта и подтверждена"
```

---

## 8. I2C-контракт: ESP32 ↔ STM32

### 8.1 Физические параметры ✅ [подтверждено]

Из `docs/i2c_global_contract.md`:

- ESP32 — **Master**, STM32 — **Slave** (адрес `0x11`, 7-бит)
- Скорость шины: **400 kHz**
- Каждая транзакция начинается с заголовка `[reg, len]`
- Нет транзакций с переменным заголовком

### 8.2 Регистровая карта STM32 ✅ [подтверждено]

| Регистр | Символ | Назначение |
|---------|--------|------------|
| `0x00` | `I2C_PACKET_TYPE_ADDR` | Тип ожидающего пакета |
| `0x01` | `I2C_REG_532_ADDR` | Данные PN532/NFC |
| `0x10` | `I2C_REG_MATRIX_PIN_ADDR` | PIN с матричной клавиатуры |
| `0x20` | `I2C_REG_WIEGAND_ADDR` | Данные Wiegand-считывателя |
| `0x30` | `I2C_REG_COUNTER_ADDR` | Сервисный счётчик |
| `0x40` | `I2C_REG_HMI_PIN_ADDR` | PIN с HMI-дисплея |
| `0x50` | `I2C_REG_HMI_MSG_ADDR` | Сообщение для HMI |
| `0x70` | `I2C_REG_HMI_ACT_ADDR` | Результат аутентификации/действия |
| `0x80` | `I2C_REG_HW_TIME_ADDR` | Чтение времени RTC |
| `0x88` | `I2C_REG_HW_TIME_SET_ADDR` | Установка времени |
| `0xE0` | `I2C_REG_CFG_ADDR` | Runtime-конфигурация |
| `0xF0` | `I2C_REG_STM32_ERROR_ADDR` | Диагностика/ошибки |

---

## 9. Сценарии использования в робототехнике

### 9.1 Умные постаматы и автоматические локеры ✅ [подтверждено]

Из `mcp/README.md` (раздел "Real-World Scenarios"):

**Стек:** STM32 (реле ячейки + NFC) → ESP32 (MQTT) → RabbitMQ → LEO4 API → AI-агент

```mermaid
graph LR
    A["AI-агент\n(LLM)"] -->|"open_cell_and_confirm\n(method_code=51)"| B["LEO4 REST API"]
    B -->|"MQTT 5.0"| C["ESP32"]
    C -->|"I2C reg=0x70\nauth result"| D["STM32F411"]
    D -->|"Relay pulse"| E["Замок ячейки"]
    D -->|"NFC scan"| F["PN532"]
    F -->|"I2C reg=0x01\nuid packet"| C
    C -->|"MQTT event"| B
    B -->|"CellOpenEvent\ntag=304"| A
```

**Ключевые компоненты:**
- `service_relay_actuator` — управление соленоидным замком
- `service_pn532_task` — сканирование NFC-метки для аутентификации
- MCP-инструмент `open_cell_and_confirm` — подтверждение физического открытия

### 9.2 Система контроля доступа ✅/🔷

**Подтверждено:** NFC-считыватель PN532 (`Core/Inc/pn532_com.h`), Wiegand-считыватель, матричная клавиатура, реле-актуатор.

**Поток аутентификации:**

```mermaid
sequenceDiagram
    participant User as Пользователь
    participant PN532 as NFC PN532
    participant STM32
    participant ESP32
    participant Cloud as LEO4 Cloud

    User->>PN532: Поднести NFC карту
    PN532->>STM32: IRQ (через TCA6408A p1)
    STM32->>STM32: PACKET_UID_532 → очередь
    STM32->>ESP32: I2C: type=0x01, reg=0x01, len=15
    ESP32->>Cloud: MQTT: uid event
    Cloud->>Cloud: Проверка прав доступа
    Cloud->>ESP32: MQTT: auth result
    ESP32->>STM32: I2C reg=0x70 [result, access_code]
    STM32->>STM32: service_relay_actuator
    STM32->>User: Открытие двери + OLED статус
```

### 9.3 Промышленный сенсорный узел 🔷 [вывод]

**Из README.md iot-rpc-rest-app:**
```
STM32. Remote starting measurements with custom parameters, sending an array of data.
ESP32, ESP-IDF. Remote send/receive to RS-485 bus.
```

**Сценарий для робота-манипулятора:**
- STM32 собирает данные датчиков по I2C/SPI с произвольными параметрами
- DS3231 обеспечивает точную временную метку измерений
- Данные передаются через ESP32 → MQTT → LEO4 API
- Телеметрия доступна через MCP-инструмент `get_telemetry`

### 9.4 SIP-коммуникация с оператором 🔷 [вывод]

**Из README.md iot-rpc-rest-app:**
```
ESP32, ESP-ADF. Remote invoke SIP-Call.
```

**Сценарий для сервисного робота:**
- Робот обнаруживает нештатную ситуацию → инициирует SIP-вызов через SIPLite
- Оператор получает аудио/видео связь с роботом
- Параллельно через MQTT/REST передаётся телеметрия
- AI-агент может анализировать ситуацию и предлагать решения оператору

### 9.5 HMI-интерфейс автономного терминала ✅ [подтверждено]

Из `Core/Inc/app_uart_dwin.h`, `dwin_gfx.h`, `docs/dwin_tx_stage3_plan_2026-03-26.md`:

- DWIN HMI-дисплей с тачскрином управляется через UART (STM32)
- `dwin_gfx` — граф. функции для отрисовки элементов интерфейса
- Сообщения от облака → ESP32 → STM32 reg=0x50 → DWIN дисплей
- OLED SSD1306 — вспомогательный дисплей статуса

### 9.6 Массовое управление парком роботов ✅ [подтверждено]

Из `mcp/README.md` (раздел "Mass Activation"):

```
AI → mass_activate(device_ids=[4619,4620,4621], method_code=20)
   → 3 concurrent POST /device-tasks/
   → Returns {total:3, success:3, failed:0}
```

- Параллельные команды для группы устройств
- Индивидуальный мониторинг через webhook-события
- TTL и приоритеты для управления очередью

### 9.7 Удалённая конфигурация и прошивка 🔷 [вывод]

**Из mcp/README.md:**
```
write_nvs(device_id=4620, namespace="wifi", key="wifi_ssid", value="MyNetwork")
```

**Сценарий:**
- Удалённая запись конфигурации в NVS ESP32 через MCP/REST
- Изменение параметров без физического доступа к роботу
- Конфигурация STM32 через I2C reg=0xE0 (`I2C_REG_CFG_ADDR`)

### 9.8 Видеопотоки: IP-камеры, FFmpeg, GStreamer и другие источники ✅ [подтверждено]

Из README.md iot-rpc-rest-app:
```
Raspberry PI. Remote start Camera-streaming custom session to WebRTC.
```

Из `main/l4_rtp_bridge.c` (12.5 KB) и `components/av_stream` репозитория `siplite` подтверждена поддержка RTP bridging и audio/video streaming.

**Поддерживаемые источники видеопотоков:**

| Источник | Протокол | Описание |
|----------|----------|----------|
| **Raspberry Pi** | RTP/WebRTC | Мощный вычислительный узел с камерой |
| **IP-камеры** (любые вендоры) | RTSP/ONVIF | Подключение к порту KSZ8863 |
| **FFmpeg** | RTP/RTSP | Генерация и транскодирование видеопотоков |
| **GStreamer** | RTP/RTSP | Пайплайны обработки видео |
| Любые RTP/RTSP источники | RTP/RTSP | Открытый протокол |

**Роль KSZ8863 Ethernet switch в видеосценариях:**
- IP-камера подключается ко второму порту KSZ8863 — трафик изолируется от основной сети
- ESP32 через `l4_rtp_bridge.c` проксирует RTP-поток на SIP-сессию
- Управление маршрутизацией видеопотоков на уровне L2

```mermaid
graph LR
    CAM["IP-камера\n(RTSP/ONVIF)"] -->|"Порт 2\nKSZ8863"| GW["ESP32\nsiplite"]
    PI["Raspberry Pi\n(FFmpeg/GStreamer)"] -->|"RTP"| GW
    GW -->|"l4_rtp_bridge\nRTP → SIP"| SIP["SIP сессия"]
    GW -->|"MQTT"| Cloud["LEO4 Cloud"]
    Cloud -->|"WebRTC"| User["Оператор"]
```



---

## 10. Ограничения и предпосылки внедрения

### 10.1 Технические ограничения

| Ограничение | Источник | Описание |
|-------------|----------|----------|
| `status=3 ≠ выполнено` | `mcp/README.md` | DONE означает доставку, не физическое выполнение |
| TTL задач | `docs/TTL.md` | Задача может истечь до доставки при потере связи |
| I2C атомарность | `docs/i2c_global_contract.md` | STM32 FSM требует полного заголовка [reg,len] до обработки |
| Буфер I2C | `docs/i2c_main_buffer_summary.md` | Ограниченный размер буфера для обмена данными |

### 10.2 Безопасность и PKI

- Каждое устройство требует уникального x509-сертификата от CA
- CA управляется через `openssl` / `pyca/cryptography` (в составе платформы)
- API-ключи не должны коммититься в репозиторий (`.env` в `.gitignore`)
- `LEO4_ALLOWED_DEVICE_IDS` — ограничение доступа AI-агента к конкретным устройствам

### 10.3 Инфраструктурные требования

| Требование | Обязательно |
|------------|-------------|
| Docker + Docker Compose | ✅ |
| Домен + TLS-сертификат (Let's Encrypt) | ✅ |
| PostgreSQL | ✅ |
| RabbitMQ с MQTT plugin | ✅ |
| CA для генерации сертификатов устройств | ✅ |
| Avahi/mDNS (для локального деплоя) | Опционально |

### 10.4 Аппаратные зависимости

- ESP32 должен поддерживать ESP-ADF для SIP-функциональности
- STM32F411CEU требует внешних компонентов (TCA6408A, DS3231, PN532, ...)
- PCB-дизайн (siplite_pcb) нужен для серийного производства аппаратных узлов
- Wiegand-совместимость требует согласования с конкретным форматом (26-bit, 34-bit, ...)

### 10.5 Миграционные пробелы в STM32 firmware ✅ [подтверждено]

Из `docs/i2c_global_contract.md`, раздел 10:

- `app_i2c_slave_addr_callback` содержит tolerant path для чтения без заголовка (legacy)
- `0x70` должен быть зафиксирован на `len=5` (в текущей реализации — relaxed)
- `0x50` (HMI message) требует явного определения фиксированной длины

---

## 11. Выводы и синтез

### 11.1 Что делает этот стек уникальным для робототехники

```mermaid
graph LR
    subgraph Преимущества["Ключевые преимущества"]
        A["End-to-end security\n(x509 + mutual TLS)"]
        B["AI-native\n(MCP server)"]
        C["Физическое подтверждение\n(poll_device_event)"]
        D["Мультипротокольность\n(MQTT + REST + I2C + SIP)"]
        E["Рой устройств\n(mass_activate + TTL queue)"]
    end
```

### 11.2 Полнота стека от сенсора до AI-агента

| Уровень | Компонент | Статус |
|---------|-----------|--------|
| Физический сенсор | PN532, DS3231, Wiegand, Matrix KBD | ✅ Реализовано |
| Актуатор | Relay (service_relay_actuator) | ✅ Реализовано |
| HMI | SSD1306 OLED, DWIN Touch | ✅ Реализовано |
| RT OS | FreeRTOS на STM32 | ✅ Реализовано |
| Шлюз | ESP32 + MQTT + I2C Master | ✅ Подтверждено |
| VoIP | SIPLite на ESP32 | ✅ Подтверждено |
| Ethernet Switch | KSZ8863 (два порта) | ✅ Подтверждено |
| OTA (ESP32) | leo4_ota.c + SW_UPDATE RPC | ✅ Подтверждено |
| OTA (STM32) | STM32_BIN_DOWNLOAD + I2C bootloader | ✅ Подтверждено |
| RTP bridge | l4_rtp_bridge.c (12.5 KB) | ✅ Подтверждено |
| Брокер | RabbitMQ + MQTT 5.0 | ✅ Реализовано |
| API | FastAPI + PostgreSQL | ✅ Реализовано |
| Security | x509 + JWT + Mutual TLS | ✅ Реализовано |
| AI/Agent | MCP server (15 tools) | ✅ Реализовано |
| PCB | siplite_pcb (не доступен) | 🔷 Предположительно |

### 11.3 Нереализованные возможности (roadmap)

Из `mcp/README.md`:

- [ ] Streaming событий через SSE-подписку (замена polling)
- [ ] `GET /device-events/incremental` для эффективного long-polling
- [ ] Управление группами устройств (теги)
- [ ] Персистентный webhook inbox (SQLite)
- [ ] OpenTelemetry tracing
- [ ] Rate limiting и circuit breaker

---

*Исследование проведено на основе публично доступных репозиториев. Репозиторий `siplite_pcb` был недоступен на момент исследования — соответствующие разделы основаны на косвенных источниках. Репозиторий `siplite` изучен полностью: все данные о шлюзе ESP32, OTA, Ethernet switch и компонентах подтверждены кодом.*
