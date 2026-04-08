# IoT RPC Device Client — .NET Framework 4.8

> **Пример RPC-клиента (Device) для .NET Framework 4.8**  
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

Этот проект представляет собой полнофункциональный пример IoT RPC-клиента (Device), написанный на C# для .NET Framework 4.8. Клиент реализует:

- **MQTT 5.0** — современный протокол для IoT с поддержкой User Properties и Correlation Data
- **TLS 1.2** — двусторонняя SSL-аутентификация (Mutual TLS)
- **Асинхронный RPC** — паттерн запрос-ответ с корреляцией
- **Polling и Trigger режимы** — гибкая инициация задач
- **Healthcheck события** — периодические keep-alive сообщения

### Особенности

| Функция | Описание |
|---------|----------|
| **MQTTnet 4.3.x** | Последняя версия с поддержкой .NET Framework 4.8 |
| **User Properties** | Передача метаданных через `correlationData`, `method_code`, `status_code` |
| **X.509 сертификаты** | Аутентификация клиента через PFX-файл |
| **Автоматический SN** | Серийный номер извлекается из CN сертификата |
| **Фоновые задачи** | Polling loop и Healthcheck loop |

---

## 🏗 Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                        DeviceClient                              │
├─────────────────────────────────────────────────────────────────┤
│  ┌───────────────┐    ┌───────────────┐    ┌───────────────┐   │
│  │   Program.cs  │───▶│ DeviceClient  │───▶│MessageHandler │   │
│  │ (Entry Point) │    │   (MQTT)      │    │  (Business)   │   │
│  └───────────────┘    └───────────────┘    └───────────────┘   │
│                              │                     │            │
│                              ▼                     ▼            │
│                       ┌─────────────────────────────────┐       │
│                       │       MQTT Broker (TLS)         │       │
│                       │   dev/<SN>/req, res, evt, ack   │       │
│                       │   srv/<SN>/tsk, rsp, cmt, eva   │       │
│                       └─────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────┘
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

- **ОС**: Windows 7 SP1+ / Windows Server 2008 R2+
- **.NET Framework**: 4.8
- **Visual Studio**: 2019 или новее (рекомендуется)

### NuGet пакеты

| Пакет | Версия | Описание |
|-------|--------|----------|
| `MQTTnet` | 4.3.3.952 | MQTT-клиент для .NET |
| `Newtonsoft.Json` | 13.0.3 | JSON-сериализация |

### Сертификаты

- **Клиентский сертификат** (PFX/PKCS#12) с закрытым ключом
- **CN (Common Name)** должен содержать серийный номер устройства
- Сертификат должен быть подписан доверенным CA сервера

---

## 📥 Установка

### Вариант 1: Visual Studio

1. Откройте `DeviceRpcClient.csproj` в Visual Studio 2019+
2. Восстановите NuGet-пакеты:
   ```
   Правый клик на Solution → Restore NuGet Packages
   ```
3. Соберите проект: `Build → Build Solution` (Ctrl+Shift+B)

### Вариант 2: Командная строка

```bash
# Переход в директорию проекта
cd examples/csharp-net48-rpc-client

# Восстановление NuGet-пакетов
nuget restore DeviceRpcClient.csproj

# Сборка
msbuild DeviceRpcClient.csproj /p:Configuration=Release
```

### Вариант 3: .NET CLI (если доступен)

```bash
dotnet restore
dotnet build
```

---

## ⚙️ Конфигурация

### App.config

Отредактируйте файл `App.config` под ваше окружение:

```xml
<appSettings>
  <!-- MQTT Broker Settings -->
  <add key="BrokerHost" value="your-mqtt-broker.com" />
  <add key="BrokerPort" value="8883" />
  
  <!-- Certificate Settings -->
  <add key="ClientCertPath" value="certificates\client_cert.pfx" />
  <add key="ClientCertPassword" value="your-certificate-password" />
  
  <!-- Timers (in seconds) -->
  <add key="ReqPollInterval" value="60" />
  <add key="HealthcheckInterval" value="300" />
</appSettings>
```

### Параметры

| Параметр | Описание | Значение по умолчанию |
|----------|----------|----------------------|
| `BrokerHost` | Адрес MQTT-брокера | `your-mqtt-broker.com` |
| `BrokerPort` | Порт MQTT-брокера (TLS) | `8883` |
| `ClientCertPath` | Путь к PFX-файлу сертификата | `certificates\client_cert.pfx` |
| `ClientCertPassword` | Пароль от сертификата | - |
| `ReqPollInterval` | Интервал поллинга задач (сек) | `60` |
| `HealthcheckInterval` | Интервал healthcheck (сек) | `300` |

### Подготовка сертификата

1. Поместите файл `client_cert.pfx` в папку `certificates\`
2. Убедитесь, что:
   - Сертификат содержит закрытый ключ
   - CN (Common Name) содержит серийный номер устройства
   - Сертификат подписан CA, которому доверяет сервер

**Пример Subject сертификата:**
```
CN=a3b1234567c10221d290825, O=MyCompany, C=RU
```

---

## 🚀 Запуск

### Visual Studio

1. Нажмите F5 или `Debug → Start Debugging`

### Командная строка

```bash
# Debug-сборка
bin\Debug\DeviceRpcClient.exe

# Release-сборка
bin\Release\DeviceRpcClient.exe
```

### Ожидаемый вывод

```
╔══════════════════════════════════════════════════════════════╗
║           IoT RPC Device Client (.NET Framework 4.8)         ║
║               MQTT 5.0 | TLS | Mutual Auth                   ║
╚══════════════════════════════════════════════════════════════╝

[CONFIG] Broker: your-mqtt-broker.com:8883
[CONFIG] Certificate: certificates\client_cert.pfx
[CONFIG] Poll interval: 60s, Healthcheck: 300s
[START] Инициализация DeviceClient...
[CERT] Subject: CN=a3b1234567c10221d290825, O=MyCompany, C=RU
[CERT] Извлечён SN из CN: a3b1234567c10221d290825
[SN] Серийный номер устройства: a3b1234567c10221d290825
[TOPICS] REQ: dev/a3b1234567c10221d290825/req, RES: dev/a3b1234567c10221d290825/res, EVT: dev/a3b1234567c10221d290825/evt
[MQTT] Подключение к your-mqtt-broker.com:8883...
[TLS] Проверка сертификата сервера: CN=mqtt.example.com
[MQTT] Результат подключения: Success
[MQTT] Подключено к MQTT-брокеру!
[MQTT] Подписка на топики выполнена.
[MQTT] Фоновые задачи запущены.
[POLL] Запущен цикл поллинга (интервал: 60 сек)
[HEALTH] Запущен цикл healthcheck (интервал: 300 сек)
[REQ] Отправлен запрос: correlation=00000000-0000-0000-0000-000000000000

════════════════════════════════════════════════════════════════
  Клиент запущен и работает. Нажмите любую клавишу для выхода.
════════════════════════════════════════════════════════════════
```

---

## 📁 Структура проекта

```
csharp-net48-rpc-client/
├── DeviceRpcClient.csproj      # Файл проекта
├── packages.config              # NuGet-зависимости
├── App.config                   # Конфигурация приложения
├── Program.cs                   # Точка входа
├── DeviceClient.cs              # Основной MQTT-клиент
├── Handlers/
│   └── MessageHandler.cs        # Обработчик входящих сообщений
├── Models/
│   └── PendingRequest.cs        # Модель pending-запроса
├── Properties/
│   └── AssemblyInfo.cs          # Метаданные сборки
├── certificates/
│   └── .gitkeep                 # Папка для PFX-сертификата
└── README.md                    # Эта документация
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

### User Properties

| Свойство | Направление | Описание |
|----------|-------------|----------|
| `correlationData` | Все | UUID для корреляции запрос-ответ |
| `method_code` | TSK, RSP | Код команды (например, `51`, `69`, `3001`) |
| `status_code` | RES | Код результата (`200`, `500`, и т.д.) |
| `ext_id` | RES | Внешний идентификатор |
| `result_id` | CMT | ID подтверждённого результата |
| `event_type_code` | EVT | Тип события (например, `44` для healthcheck) |

---

## 🔧 Расширение функциональности

### Добавление обработчика команд

Откройте `Handlers/MessageHandler.cs` и измените метод `ExecuteTaskAsync`:

```csharp
private async Task<JObject> ExecuteTaskAsync(string methodCode, JObject parameters)
{
    Console.WriteLine($"[EXEC] Выполнение задачи: method={methodCode}");

    // Маршрутизация по коду метода
    switch (methodCode)
    {
        case "51":
            return await HandleOpenCommand(parameters);
        
        case "52":
            return await HandleCloseCommand(parameters);
        
        case "69":
            return await HandleSpecialCommand(parameters);
        
        default:
            return new JObject
            {
                ["status"] = "error",
                ["message"] = $"Unknown method: {methodCode}"
            };
    }
}

private async Task<JObject> HandleOpenCommand(JObject parameters)
{
    // Ваша логика открытия
    await Task.Delay(100);
    return new JObject { ["status"] = "opened" };
}

private async Task<JObject> HandleCloseCommand(JObject parameters)
{
    // Ваша логика закрытия
    await Task.Delay(100);
    return new JObject { ["status"] = "closed" };
}
```

### Отправка кастомного события

```csharp
// В любом месте кода, где доступен DeviceClient:
await client.SendEventAsync(
    eventTypeCode: 99,
    eventData: new {
        message = "Sensor triggered",
        value = 42.5,
        timestamp = DateTime.UtcNow
    },
    devEventId: "sensor-001"
);
```

---

## ❓ FAQ

### Q: Почему используется MQTTnet 4.3.x, а не 5.x?

MQTTnet 5.x требует .NET 6+ и не поддерживает .NET Framework 4.8. Версия 4.3.3.952 — последняя стабильная версия для .NET Framework.

### Q: Как изменить интервал поллинга?

Измените значение `ReqPollInterval` в `App.config` или передайте параметр в конструктор `DeviceClient`.

### Q: Сертификат не загружается

- Убедитесь, что PFX-файл содержит закрытый ключ
- Проверьте правильность пароля
- Запустите приложение от имени администратора (для доступа к хранилищу ключей)

### Q: Как отладить TLS-соединение?

Добавьте логирование в `CertificateValidationHandler`:

```csharp
CertificateValidationHandler = context =>
{
    Console.WriteLine($"[TLS] Subject: {context.Certificate?.Subject}");
    Console.WriteLine($"[TLS] Issuer: {context.Certificate?.Issuer}");
    Console.WriteLine($"[TLS] Chain Status: {string.Join(", ", context.Chain?.ChainStatus?.Select(s => s.Status) ?? Array.Empty<X509ChainStatusFlags>())}");
    return true;
}
```

---

## 📚 Документация

- [Протокол MQTT RPC](../../docs/mqtt-rpc-protocol.md)
- [Клиентский флоу](../../docs/mqtt-rpc-client-flow.md)
- [Интеграция с сервером](../../docs/server-integration-guide.md)

---

## 📝 Лицензия

MIT License

---

**Автор**: IoT Platform Team  
**Версия**: 1.0.0  
**Дата**: 2025
