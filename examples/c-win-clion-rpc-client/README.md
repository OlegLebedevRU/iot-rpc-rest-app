# IoT RPC Device Client — C (Windows 10+ / CLion)

> **Пример RPC-клиента (Device) на языке C**  
> Реализация асинхронного протокола MQTT 5.0 для взаимодействия IoT-устройства с облачным сервером.

---

## 📋 Оглавление

- [Обзор](#-обзор)
- [Архитектура](#-архитектура)
- [Требования](#-требования)
- [Установка](#-установка)
- [Конфигурация](#️-конфигурация)
- [Запуск](#-запуск)
- [Структура проекта](#-структура-проекта)
- [Протокол RPC](#-протокол-rpc)
- [Расширение функциональности](#-расширение-функциональности)
- [FAQ](#-faq)

---

## 📖 Обзор

Этот проект представляет собой полнофункциональный пример IoT RPC-клиента (Device), написанный на **чистом C (C11)** для Windows 10+. Клиент реализует:

- **MQTT 5.0** — современный протокол для IoT с поддержкой User Properties и Correlation Data
- **TLS 1.2** — двусторонняя SSL-аутентификация (Mutual TLS)
- **Асинхронный RPC** — паттерн запрос-ответ с корреляцией
- **Polling и Trigger режимы** — гибкая инициация задач
- **Healthcheck события** — периодические keep-alive сообщения

### Особенности

| Функция | Описание |
|---------|----------|
| **Eclipse Paho MQTT C** | Асинхронный MQTT-клиент с полной поддержкой MQTT 5.0 |
| **Нативный Correlation Data** | Используется нативное свойство MQTT 5 `CorrelationData` |
| **User Properties** | Передача метаданных: `method_code`, `status_code`, `event_type_code` |
| **OpenSSL** | Извлечение SN из CN сертификата + TLS-аутентификация |
| **Автоматический SN** | Серийный номер извлекается из CN клиентского PEM-сертификата |
| **Фоновые потоки** | Polling loop и Healthcheck loop через `_beginthreadex` (Win) / `pthread` (POSIX) |
| **CMake + CLion** | Готовый проект для IDE CLion (CMake-based) |

---

## 🏗 Архитектура

```
┌──────────────────────────────────────────────────────────────────┐
│                      iot_rpc_device_client                        │
├──────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐   ┌────────────────┐   ┌───────────────────┐   │
│  │   main.c    │──▶│ device_client  │──▶│ message_handler   │   │
│  │ (Entry Pt.) │   │ (MQTT + TLS)   │   │ (Business Logic)  │   │
│  └─────────────┘   └────────────────┘   └───────────────────┘   │
│                            │                      │              │
│                            ▼                      ▼              │
│                ┌─────────────────┐      ┌──────────────────┐     │
│                │  cert_utils.c   │      │    config.h       │    │
│                │ (OpenSSL / CN)  │      │  (Настройки)      │    │
│                └─────────────────┘      └──────────────────┘     │
│                            │                                     │
│                            ▼                                     │
│                ┌──────────────────────────────────────┐          │
│                │       MQTT Broker (TLS 1.2)          │          │
│                │   dev/<SN>/req, res, evt, ack        │          │
│                │   srv/<SN>/tsk, rsp, cmt, eva        │          │
│                └──────────────────────────────────────┘          │
└──────────────────────────────────────────────────────────────────┘
                             │
                             ▼
                   ┌───────────────────┐
                   │   Cloud Server    │
                   │   (Backend API)   │
                   └───────────────────┘
```

---

## 📌 Требования

### Системные требования

- **ОС**: Windows 10 или новее
- **IDE**: JetBrains CLion 2022+ (или любая IDE с поддержкой CMake)
- **Компилятор**: MSVC (Visual Studio 2019+), MinGW-w64 или Clang
- **CMake**: 3.16+
- **Git**: Для FetchContent (скачивание Paho MQTT C)

### Зависимости

| Библиотека | Версия | Назначение |
|------------|--------|------------|
| **Eclipse Paho MQTT C** | 1.3.14 | Асинхронный MQTT-клиент (MQTTv5) |
| **OpenSSL** | 1.1.1+ / 3.x | TLS, парсинг X.509 сертификатов |

> 💡 Paho MQTT C автоматически скачивается через CMake FetchContent.  
> OpenSSL необходимо установить отдельно (см. раздел «Установка»).

### Сертификаты

- **CA-сертификат** (`ca_cert.pem`) — корневой сертификат для проверки сервера
- **Клиентский сертификат** (`client_cert.pem`) — PEM-файл с сертификатом
- **Приватный ключ** (`client_key.pem`) — PEM-файл с ключом (без пароля)
- **CN (Common Name)** должен содержать серийный номер устройства

---

## 📥 Установка

### 1. Установка OpenSSL на Windows

**Вариант A: Через vcpkg**
```powershell
git clone https://github.com/microsoft/vcpkg.git
cd vcpkg
.\bootstrap-vcpkg.bat
.\vcpkg install openssl:x64-windows
```

**Вариант B: Предсобранные бинарники**
- Скачайте с https://slproweb.com/products/Win32OpenSSL.html
- Установите Win64 OpenSSL (полная версия, не Light)
- Добавьте путь в `CMAKE_PREFIX_PATH` или переменную окружения `OPENSSL_ROOT_DIR`

### 2. Открытие в CLion

1. Откройте CLion
2. `File → Open` → выберите папку `c-win-clion-rpc-client`
3. CLion автоматически обнаружит `CMakeLists.txt` и настроит проект

### 3. Настройка CMake в CLion

Перейдите в `Settings → Build → CMake` и добавьте CMake Options:

```
-DOPENSSL_ROOT_DIR=C:/Program Files/OpenSSL-Win64
```

Или, если используете vcpkg:
```
-DCMAKE_TOOLCHAIN_FILE=C:/vcpkg/scripts/buildsystems/vcpkg.cmake
-DUSE_VCPKG=ON
```

### 4. Сборка

- В CLion: `Build → Build Project` (Ctrl+F9)
- Или из командной строки:

```powershell
cd examples\c-win-clion-rpc-client
mkdir build && cd build
cmake .. -DOPENSSL_ROOT_DIR="C:/Program Files/OpenSSL-Win64"
cmake --build . --config Release
```

---

## ⚙️ Конфигурация

### src/config.h

Отредактируйте файл `src/config.h` перед сборкой:

```c
/* MQTT Broker */
#define BROKER_HOST         "your-mqtt-broker.com"
#define BROKER_PORT         8883
#define BROKER_KEEPALIVE    60

/* Сертификаты */
#define CA_CERT_PATH        "certificates\\ca_cert.pem"
#define CLIENT_CERT_PATH    "certificates\\client_cert.pem"
#define CLIENT_KEY_PATH     "certificates\\client_key.pem"

/* Таймеры (секунды) */
#define REQ_POLL_INTERVAL   60
#define HEALTHCHECK_INTERVAL 300
```

### Параметры

| Параметр | Описание | Значение по умолчанию |
|----------|----------|----------------------|
| `BROKER_HOST` | Адрес MQTT-брокера | `your-mqtt-broker.com` |
| `BROKER_PORT` | Порт MQTT-брокера (TLS) | `8883` |
| `CA_CERT_PATH` | Путь к CA-сертификату | `certificates\ca_cert.pem` |
| `CLIENT_CERT_PATH` | Путь к клиентскому сертификату | `certificates\client_cert.pem` |
| `CLIENT_KEY_PATH` | Путь к приватному ключу | `certificates\client_key.pem` |
| `REQ_POLL_INTERVAL` | Интервал поллинга (сек) | `60` |
| `HEALTHCHECK_INTERVAL` | Интервал healthcheck (сек) | `300` |

### Подготовка сертификатов

1. Поместите PEM-файлы в папку `certificates\`
2. Убедитесь, что:
   - `client_cert.pem` содержит сертификат в формате PEM
   - `client_key.pem` содержит приватный ключ (без пароля)
   - CN (Common Name) содержит серийный номер устройства
   - Сертификат подписан CA, которому доверяет сервер

**Пример Subject сертификата:**
```
CN=a3b1234567c10221d290825, O=MyCompany, C=RU
```

---

## 🚀 Запуск

### CLion

1. Выберите конфигурацию `iot_rpc_device_client` в верхней панели
2. Нажмите ▶ Run (Shift+F10) или 🐛 Debug (Shift+F9)

### Командная строка

```powershell
cd build\Release
.\iot_rpc_device_client.exe
```

### Ожидаемый вывод

```
================================================================
       IoT RPC Device Client  (C / Paho MQTT 5.0)
       Windows 10+ | TLS 1.2 | Mutual Auth | CLion
================================================================

[START] Инициализация DeviceClient...
[CERT] Subject CN (SN): a3b1234567c10221d290825
[SN] Серийный номер устройства: a3b1234567c10221d290825
[TOPICS] REQ: dev/a3b1234567c10221d290825/req, RES: dev/a3b1234567c10221d290825/res, EVT: dev/a3b1234567c10221d290825/evt
[MQTT] Подключение к ssl://your-mqtt-broker.com:8883...
[MQTT] Подключено к MQTT-брокеру!
[MQTT] Подписка на топики выполнена.
[MQTT] Фоновые задачи запущены.
[POLL] Запущен цикл поллинга (интервал: 60 сек)
[HEALTH] Запущен цикл healthcheck (интервал: 300 сек)
[REQ] Отправлен запрос: correlation=00000000-0000-0000-0000-000000000000

================================================================
  Клиент запущен и работает. Нажмите Enter для выхода.
================================================================
```

---

## 📁 Структура проекта

```
c-win-clion-rpc-client/
├── CMakeLists.txt              # CMake-проект (CLion)
├── README.md                   # Эта документация
├── src/
│   ├── main.c                  # Точка входа
│   ├── device_client.c/.h      # MQTT-клиент, TLS, publish, потоки
│   ├── message_handler.c/.h    # Обработка входящих сообщений
│   ├── cert_utils.c/.h         # Извлечение CN из X.509 (OpenSSL)
│   └── config.h                # Все настраиваемые параметры
└── certificates/
    └── .gitkeep                # Папка для PEM-сертификатов
```

---

## 📡 Протокол RPC

### Топики

| Направление | Топик | Назначение |
|-------------|-------|------------|
| Device → Server | `dev/<SN>/req` | Запрос параметров задачи / поллинг |
| Device → Server | `dev/<SN>/ack` | Подтверждение получения TSK |
| Device → Server | `dev/<SN>/res` | Результат выполнения задачи |
| Device → Server | `dev/<SN>/evt` | Асинхронное событие |
| Server → Device | `srv/<SN>/tsk` | Анонс задачи (Trigger mode) |
| Server → Device | `srv/<SN>/rsp` | Параметры задачи |
| Server → Device | `srv/<SN>/cmt` | Подтверждение получения результата |
| Server → Device | `srv/<SN>/eva` | Подтверждение события |

### Жизненный цикл RPC

```
[Trigger Mode]
   TSK  ← Сервер анонсирует задачу
    ↓
   ACK  → Устройство подтверждает (опционально)
    ↓
   REQ  → Устройство запрашивает параметры
    ↓
   RSP  ← Сервер отправляет параметры
    ↓
   RES  → Устройство отправляет результат
    ↓
   CMT  ← Сервер подтверждает получение

[Polling Mode]
   REQ  → Устройство поллит (zero UUID)
    ↓
   RSP  ← Сервер отправляет задачу (если есть)
    ↓
   RES  → Устройство отправляет результат
    ↓
   CMT  ← Сервер подтверждает
```

### MQTT 5 Properties

| Свойство | Направление | Описание |
|----------|-------------|----------|
| `CorrelationData` | Все | UUID для корреляции запрос-ответ (нативное MQTT 5 свойство) |
| `method_code` (UP) | TSK, RSP | Код команды (`51`, `69`, `3001`) |
| `status_code` (UP) | RES | Код результата (`200`, `500`, и т.д.) |
| `ext_id` (UP) | RES | Внешний идентификатор |
| `result_id` (UP) | CMT | ID подтверждённого результата |
| `event_type_code` (UP) | EVT | Тип события (`44` = healthcheck) |
| `dev_event_id` (UP) | EVT | Идентификатор события на устройстве |
| `dev_timestamp` (UP) | EVT | Временная метка (Unix timestamp) |

> **UP** = User Property (MQTT 5)

---

## 🔧 Расширение функциональности

### Добавление обработчика команд

Откройте `src/message_handler.c` и измените функцию `handle_task_response`:

```c
static void handle_task_response(MessageHandlerCtx *ctx,
                                 const char *corr_data,
                                 MQTTAsync_message *msg)
{
    char method_code[32];
    get_user_property(msg, "method_code", method_code, sizeof(method_code));

    /* Маршрутизация по коду метода */
    if (strcmp(method_code, "51") == 0) {
        /* Команда «Открыть» */
        handle_open_command(ctx, corr_data, msg);
    } else if (strcmp(method_code, "52") == 0) {
        /* Команда «Закрыть» */
        handle_close_command(ctx, corr_data, msg);
    } else {
        /* Неизвестная команда */
        const char *err = "{\"status\":\"error\",\"message\":\"Unknown method\"}";
        device_client_send_result(ctx->client, ctx->serial_number,
                                  corr_data, err);
    }
}
```

### Отправка кастомного события

```c
/* В любом месте, где доступен g_client и g_sn: */
const char *sensor_json =
    "{\"message\":\"Sensor triggered\",\"value\":42.5}";
device_client_send_event(g_client, g_sn, 99, sensor_json);
```

---

## ❓ FAQ

### Q: Почему используется Paho MQTT C, а не другая библиотека?

Eclipse Paho MQTT C — зрелая, кроссплатформенная библиотека с полной поддержкой MQTT 5.0, включая User Properties и Correlation Data. Она активно поддерживается Eclipse Foundation.

### Q: Как использовать PFX-сертификат вместо PEM?

Paho MQTT C работает с PEM-файлами. Конвертируйте PFX → PEM:
```powershell
# Извлечение сертификата
openssl pkcs12 -in client.pfx -clcerts -nokeys -out client_cert.pem

# Извлечение ключа
openssl pkcs12 -in client.pfx -nocerts -nodes -out client_key.pem
```

### Q: Как собрать без FetchContent (офлайн)?

Установите Paho MQTT C через vcpkg и используйте флаг:
```
cmake .. -DUSE_VCPKG=ON -DCMAKE_TOOLCHAIN_FILE=<vcpkg>/scripts/buildsystems/vcpkg.cmake
```

### Q: Можно ли скомпилировать под Linux/macOS?

Да, код полностью кроссплатформенный — используются условные компиляции `#ifdef _WIN32` для системно-зависимых частей (потоки, sleep, UTF-8 консоль).

### Q: Как добавить JSON-парсинг?

Рекомендуется использовать [cJSON](https://github.com/DaveGamble/cJSON) — легковесная C-библиотека для JSON. Добавьте через FetchContent:

```cmake
FetchContent_Declare(cjson
    GIT_REPOSITORY https://github.com/DaveGamble/cJSON.git
    GIT_TAG v1.7.18)
FetchContent_MakeAvailable(cjson)
target_link_libraries(${PROJECT_NAME} PRIVATE cjson)
```

---

## 📚 Документация

- [Протокол MQTT RPC](../../docs/mqtt-rpc-protocol.md)
- [Клиентский флоу](../../docs/mqtt-rpc-client-flow.md)
- [Пример на Python](../mqtt5-paho-full-rpc-client-example.py)
- [Пример на C# (.NET 4.8)](../csharp-net48-rpc-client/README.md)

---

## 📝 Лицензия

MIT License

---

**Автор**: IoT Platform Team  
**Версия**: 1.0.0  
**Дата**: 2025
