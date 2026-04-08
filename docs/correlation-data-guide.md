

# Руководство по использованию Correlation Data в клиентах IoT RPC

> **Файл:** `docs/correlation-data-guide.md`  
> **Версия:** 1.0  
> **Дата:** 2025  
> **Автор:** Oleg_

---

## Введение

Данный документ посвящён аспектам передачи и обработки поля `correlationData` в рамках прикладного IoT RPC-протокола (описанного в [`docs/mqtt-rpc-protocol.md`](./mqtt-rpc-protocol.md)).

`correlationData` — это **сквозной UUID**, который идентифицирует весь RPC-цикл от начала до конца: TSK → ACK → REQ → RSP → RES → CMT. Он позволяет серверу и устройству бесгосударственно (stateless) сопоставлять запросы и ответы без хранения промежуточного состояния на транспортном уровне.

### Почему это критично

Разные клиентские библиотеки (Python paho, C# MQTTnet .NET 4.8, ESP-IDF и др.) реализуют поддержку `CorrelationData` из спецификации MQTT 5 по-разному. Кроме того, брокер **RabbitMQ с нативным MQTT-плагином** при трансляции MQTT 5 ↔ AMQP 0.9.1 по-разному обрабатывает разные форматы `CorrelationData`. Если `correlationData` передаётся неправильно или не может быть распознано сервером, RPC-цикл прерывается: задача не переходит в состояние PENDING, результат не сохраняется, CMT не отправляется.

---

## Предпочтительный способ передачи: нативный MQTT 5 CorrelationData

**Рекомендуемый подход** — передавать `correlationData` через нативное поле `CorrelationData` из спецификации MQTT 5. Это поле напрямую транслируется RabbitMQ MQTT-плагином в поле `correlation_id` AMQP-сообщения, что является самым надёжным и производительным путём.

### Формат значения

UUID следует кодировать как **UTF-8 строку** (36 символов, стандартный формат `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`), а **не** как 16-байтовое бинарное представление. Строковый формат гарантирует прозрачную трансляцию в AMQP `shortstr` без потерь.

**Пример: Python paho-mqtt**

```python
import uuid
import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes

# Генерация UUID
corr_id = str(uuid.uuid4())  # например, "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

# Публикация с нативным CorrelationData
props = mqtt.Properties(PacketTypes.PUBLISH)
props.CorrelationData = corr_id.encode("utf-8")  # bytes — UTF-8 строка UUID

client.publish(
    topic=f"dev/{sn}/req",
    payload="",
    qos=1,
    properties=props
)
```

**Пример: чтение CorrelationData на стороне клиента**

```python
def on_message(client, userdata, msg):
    if hasattr(msg.properties, 'CorrelationData'):
        corr_id = msg.properties.CorrelationData.decode("utf-8")
        print(f"Native CorrelationData: {corr_id}")
```

### Почему нативный путь предпочтителен

| Характеристика | Нативный `CorrelationData` | User Property |
|---|---|---|
| Маппинг в AMQP | → `properties.correlation_id` (нативное поле) | → `headers["correlationData"]` |
| Надёжность | Высокая, прямая трансляция | Зависит от реализации брокера |
| Производительность | Оптимальная | Доп. обработка headers |
| Совместимость с MQTT 3.1.1 | ❌ Нет (только MQTT 5) | ❌ Нет (только MQTT 5) |
| Поддержка в paho | ✅ Полная | ✅ Есть |
| Поддержка в MQTTnet .NET 4.8 | ⚠️ Ограниченная | ✅ Надёжная |

---

## Альтернативный способ: User Properties

Когда нативный `CorrelationData` не поддерживается или ненадёжен (например, в MQTTnet для .NET Framework 4.8), UUID можно передавать как **User Property** с ключом `correlationData`.

### Как это работает

При публикации MQTT 5-сообщения с User Property `correlationData = "..."`, RabbitMQ MQTT-плагин транслирует эту пару ключ-значение в AMQP-заголовок `headers["correlationData"]`. Сервер обрабатывает это через резервную ветку в `corr_id_getter_dep`.

**Пример: C# MQTTnet (.NET Framework 4.8)**

```csharp
string correlationData = Guid.NewGuid().ToString(); // "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

var message = new MqttApplicationMessageBuilder()
    .WithTopic($"dev/{serialNumber}/req")
    .WithPayload("")
    .WithQualityOfServiceLevel(MqttQualityOfServiceLevel.AtLeastOnce)
    .WithUserProperty("correlationData", correlationData)  // User Property вместо нативного поля
    .Build();

await _mqttClient.PublishAsync(message);
```

**Пример: чтение со стороны клиента (C#)**

```csharp
// Сначала проверяем User Properties (надёжный путь для .NET 4.8)
var correlationData = args.ApplicationMessage.UserProperties?
    .FirstOrDefault(p => p.Name == "correlationData")?.Value ?? "";

// Резервный вариант: нативное CorrelationData (если поддерживается)
if (string.IsNullOrEmpty(correlationData) && args.ApplicationMessage.CorrelationData != null)
{
    correlationData = Encoding.UTF8.GetString(args.ApplicationMessage.CorrelationData);
}
```

> **Примечание:** Сервер поддерживает оба способа через цепочку fallback в `corr_id_getter_dep` (см. раздел [Серверная адаптация](#серверная-адаптация)).

---

## Особенности RabbitMQ MQTT Plugin (MQTT 5 ↔ AMQP 0.9.1)

RabbitMQ использует нативный MQTT-плагин для трансляции сообщений между MQTT 5 и AMQP 0.9.1. Это вводит нюансы в обработку `CorrelationData`.

### Трансляция нативного MQTT 5 `CorrelationData` → AMQP

| Тип значения | Длина/Формат | Расположение в AMQP | Примечания |
|---|---|---|---|
| `utf8` | `shortstr` (≤ 256 байт) | `properties.correlation_id` | Прямая передача как строка — **рекомендуемый формат** |
| `utf8` | > 256 байт | `headers["x-correlation-id"]` | Перемещается в заголовки как `longstr` |
| `uuid` (16-байтный binary) | 16 байт | `properties.correlation_id` | Конвертируется в строку вида `"urn:uuid:550e8400-..."` |
| `ulong` | 64-bit integer | `properties.correlation_id` | Конвертируется в текстовое представление числа |
| `binary` | Произвольный binary | `headers["x-correlation-id"]` | Передаётся как бинарные данные в заголовках |

> **Ограничение AMQP:** поле `correlation_id` в AMQP 0.9.1 является `shortstr` и ограничено **256 байтами**. Значения, превышающие этот лимит (включая произвольный binary), перемещаются в `headers["x-correlation-id"]`.

### Трансляция MQTT 5 User Properties → AMQP

Каждая User Property из MQTT 5 PUBLISH-сообщения транслируется в заголовок AMQP-сообщения с тем же ключом и значением:

```
MQTT 5 UserProperty("correlationData", "a1b2c3d4-...") 
    → AMQP headers["correlationData"] = "a1b2c3d4-..."

MQTT 5 UserProperty("method_code", "51")
    → AMQP headers["method_code"] = "51"
```

### Как сервер отправляет correlationData клиентам

Сервер (Python backend через AMQP → RabbitMQ → MQTT) дублирует `correlationData` **двумя путями одновременно**:

```python
# Из app-service/core/services/device_task_processing.py
await topic_publisher.publish(
    routing_key=task_device_topic,
    message=notify,
    correlation_id=stask.id,          # → AMQP correlation_id → MQTT CorrelationData
    headers={
        "correlationData": str(stask.id),  # → AMQP headers → MQTT User Property
        "method_code": str(method_code),
    },
)
```

В результате клиент получает `correlationData`:
- В нативном поле `CorrelationData` MQTT 5 (для paho и аналогичных клиентов)
- В User Property `correlationData` (для C# MQTTnet .NET 4.8 и других)

---

## Серверная адаптация

Серверная функция `corr_id_getter_dep` в `app-service/core/topologys/fs_depends.py` реализует устойчивую цепочку fallback для извлечения `correlationData` из любого поддерживаемого источника.

### Цепочка fallback (в порядке приоритета)

```
msg.correlation_id
    ↓ (если пусто или не парсится)
headers["x-correlation-id"]
    ↓ (если отсутствует или не парсится)
headers["correlationData"]
    ↓ (если отсутствует или не парсится)
corr_id = None
```

#### 1. `msg.correlation_id` — нативное AMQP-свойство (высший приоритет)

Покрывает:
- Python paho с нативным `props.CorrelationData = uuid_str.encode("utf-8")`
- RabbitMQ-конверсии из 16-байтового binary UUID → строка `"urn:uuid:..."`
- RabbitMQ-конверсии из `ulong` → строка-число

#### 2. `headers["x-correlation-id"]` — переполнение RabbitMQ

Покрывает:
- Нативный `CorrelationData` длиной > 256 байт (RabbitMQ перемещает в headers)
- Произвольные бинарные данные в `CorrelationData` (RabbitMQ помещает в `x-correlation-id`)

#### 3. `headers["correlationData"]` — User Property (путь C# MQTTnet .NET 4.8)

Покрывает:
- C# MQTTnet (`.WithUserProperty("correlationData", uuid_str)`)
- Любые клиенты, передающие `correlationData` через User Properties

### Парсинг UUID в каждом источнике

Для каждого источника применяется вспомогательная функция `_try_parse_uuid`:

```python
# app-service/core/topologys/fs_depends.py

def _try_parse_uuid(value) -> uuid.UUID | None:
    if isinstance(value, str):
        try:
            return uuid.UUID(value)        # Стандартная строка "a1b2-..."
        except (ValueError, AttributeError):
            pass
    if isinstance(value, (bytes, bytearray)) and len(value) == 16:
        try:
            return uuid.UUID(bytes=bytes(value))  # 16-байтовый бинарный UUID
        except (ValueError, AttributeError):
            pass
    return None
```

Порядок попыток:
1. **Строка → `uuid.UUID(str)`** — стандартный 36-символьный формат (`"a1b2c3d4-e5f6-..."`) и `"urn:uuid:..."` (RabbitMQ auto-convert из binary uuid)
2. **Бинарные данные, ровно 16 байт → `uuid.UUID(bytes=...)`** — нативный binary UUID

Если ни один вариант не подошёл, `corr_id` устанавливается в `None`.

---

## Известные несовместимости и подводные камни

### MQTTnet (.NET Framework 4.8)

MQTTnet для .NET Framework 4.8 не поддерживает надёжную установку нативного `CorrelationData` через builder API для MQTT 5 PUBLISH-пакетов. Метод `.WithCorrelationData()` может отсутствовать или вести себя непредсказуемо. **Используйте `.WithUserProperty("correlationData", uuid_str)` вместо нативного поля.**

```csharp
// ✅ Правильно для .NET 4.8
.WithUserProperty("correlationData", correlationData)

// ⚠️ Может не работать в .NET 4.8
// .WithCorrelationData(Encoding.UTF8.GetBytes(correlationData))
```

### Бинарный UUID (16 байт) vs строковый UUID (36 символов)

Если клиент отправляет `CorrelationData` как **16-байтовый бинарный UUID** (например, `uuid.uuid4().bytes`):
- RabbitMQ помещает его в `correlation_id`, конвертируя в строку вида `"urn:uuid:550e8400-e29b-41d4-a716-446655440000"`
- Сервер успешно парсит это через `uuid.UUID("urn:uuid:...")`

Если же клиент передаёт строковый UUID (`uuid_str.encode("utf-8")`, 36 байт):
- RabbitMQ помещает его в `correlation_id` как есть (< 256 байт — `shortstr`)
- Сервер успешно парсит через `uuid.UUID(str)`

**Важно:** предыдущая версия сервера пыталась парсить строковый UUID через `uuid.UUID(bytes=str.encode())`, что всегда падало с `ValueError`, т.к. строка `"a1b2-..."` (36 байт после encode) ≠ 16 байт бинарного UUID. После исправления сервер корректно обрабатывает строковый UUID через `uuid.UUID(str)`.

### Пустой или отсутствующий correlationData

- `corr_id = None` — результат, если ни один источник не содержит валидного UUID
- Для **поллинга** (нулевой UUID `00000000-0000-0000-0000-000000000000`): сервер вернёт `nop_resp` — это ожидаемое поведение при отсутствии задач
- Для **выполнения задачи**: `corr_id = None` прерывает RPC-цикл — задача не будет найдена, результат не сохранится

### MQTT 3.1.1 клиенты

Протокол MQTT версии 3.1.1 **не поддерживает** ни `CorrelationData`, ни `User Properties`. Такие клиенты несовместимы с данным протоколом.

### Polling с нулевым UUID

При поллинге (`correlationData = "00000000-0000-0000-0000-000000000000"`) сервер:
- Успешно парсит UUID через `uuid.UUID("00000000-0000-0000-0000-000000000000")`
- В `DeviceTasksService.select()` возвращает `nop_resp` (`{"method_code":0}`) если задач нет

Это ожидаемое поведение.

---

## Рекомендации для разработчиков клиентов

### Таблица решений по клиентским библиотекам

| Клиентская библиотека | Рекомендуемый метод | Пример |
|---|---|---|
| Python paho-mqtt | Нативный `CorrelationData` | `props.CorrelationData = uuid_str.encode("utf-8")` |
| C# MQTTnet (.NET 4.8) | User Property | `.WithUserProperty("correlationData", uuid_str)` |
| C# MQTTnet (.NET 6+) | Нативный `CorrelationData` предпочтительно, User Property как fallback | `.WithCorrelationData(Encoding.UTF8.GetBytes(uuid_str))` |
| ESP-IDF (ESP32) | Нативный `CorrelationData` | Устанавливается в MQTT 5 publish properties |
| MQTTX (тестирование) | Нативное поле Correlation Data в UI | Вводить UUID-строку в поле Correlation Data |

### Отправка correlationData

**Python paho — нативный путь (рекомендуется):**

```python
import uuid
import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes

corr_id = str(uuid.uuid4())

props = mqtt.Properties(PacketTypes.PUBLISH)
props.CorrelationData = corr_id.encode("utf-8")  # UTF-8 строка UUID

client.publish(topic=f"dev/{sn}/req", payload="", qos=1, properties=props)
```

**C# MQTTnet .NET 4.8 — через User Property:**

```csharp
string corrId = Guid.NewGuid().ToString();

var msg = new MqttApplicationMessageBuilder()
    .WithTopic($"dev/{sn}/req")
    .WithPayload("")
    .WithQualityOfServiceLevel(MqttQualityOfServiceLevel.AtLeastOnce)
    .WithUserProperty("correlationData", corrId)
    .Build();

await client.PublishAsync(msg);
```

### Чтение correlationData из сообщений сервера

Так как сервер дублирует `correlationData` и в нативном поле, и в User Property, клиент должен проверять оба источника:

**Python paho:**

```python
def on_message(client, userdata, msg):
    corr_id = None

    # 1. Предпочтительно: User Property (всегда присутствует от сервера)
    if hasattr(msg.properties, 'UserProperty'):
        user_props = dict(msg.properties.UserProperty)
        corr_id = user_props.get("correlationData")

    # 2. Резервный: нативное поле CorrelationData
    if not corr_id and hasattr(msg.properties, 'CorrelationData'):
        corr_id = msg.properties.CorrelationData.decode("utf-8")
```

**C# MQTTnet .NET 4.8:**

```csharp
// 1. Предпочтительно: User Property
var correlationData = args.ApplicationMessage.UserProperties?
    .FirstOrDefault(p => p.Name == "correlationData")?.Value ?? "";

// 2. Резервный: нативное CorrelationData
if (string.IsNullOrEmpty(correlationData) && args.ApplicationMessage.CorrelationData != null)
{
    correlationData = Encoding.UTF8.GetString(args.ApplicationMessage.CorrelationData);
}
```

---

## Диагностика проблем

### Проверка correlationData в логах сервера

Сервер записывает информацию о полученных `correlationData` в лог-файл `depends_broker.log`:

```
# Успешное получение через нативный correlation_id
DEBUG: Received msg.correlation_id = a1b2c3d4-e5f6-7890-abcd-ef1234567890

# Успешное получение через x-correlation-id
INFO: Received headers.x-correlation-id = a1b2c3d4-e5f6-7890-abcd-ef1234567890

# Успешное получение через User Property
INFO: Received headers.correlationData = a1b2c3d4-e5f6-7890-abcd-ef1234567890

# Предупреждение: correlationData не найден
WARNING: Received from device no corr data, headers = {...}

# Предупреждение: исключение при парсинге
WARNING: Received from device no corr data, exception = ...
```

### Типичные признаки проблем

| Симптом | Возможная причина |
|---|---|
| Задача не переходит в PENDING после ACK | `corr_id = None` в `corr_id_getter_dep` при обработке ACK |
| `nop_resp` (`{"method_code":0}`) вместо данных задачи | Сервер не нашёл задачу по `corr_id = None` |
| Результат не сохраняется, CMT не приходит | `corr_id = None` при обработке RES |
| `WARNING: Received from device no corr data` в логах | Ни один источник не содержит валидного UUID |

### RabbitMQ Management UI

Для диагностики можно инспектировать сообщения в очередях через **RabbitMQ Management UI** (порт 15672 по умолчанию):

1. Открыть раздел **Queues** → выбрать очередь устройства
2. Нажать **Get messages** (режим `Ack mode: Nack message requeue true` для неразрушающего просмотра)
3. Проверить поля сообщения:
   - **Properties → correlation_id** — нативное AMQP поле (должно содержать UUID-строку при использовании нативного CorrelationData)
   - **Headers** — заголовки сообщения (должны содержать `correlationData` при использовании User Properties)

### Что проверить при отладке нового клиента

1. **Формат UUID**: убедитесь, что передаётся строка вида `"xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"` (36 символов), а не 16-байтовый binary
2. **Метод передачи**: проверьте, какой путь использует ваша библиотека — нативный `CorrelationData` или User Property
3. **Логи сервера**: `depends_broker.log` покажет, из какого источника был получен UUID и был ли он успешно распознан
4. **RabbitMQ UI**: инспекция очереди позволит увидеть реальные значения `correlation_id` и `headers` после трансляции MQTT → AMQP

---

## Связанные документы

- [`docs/mqtt-rpc-protocol.md`](./mqtt-rpc-protocol.md) — полная спецификация протокола, включая RPC-цикл и структуру топиков
- [`examples/mqtt5-paho-full-rpc-client-example.py`](../examples/mqtt5-paho-full-rpc-client-example.py) — полный пример Python paho клиента
- [`examples/mini-native-paho-mqttv5-corrdata-client.py`](../examples/mini-native-paho-mqttv5-corrdata-client.py) — минимальный пример с нативным CorrelationData
- [`examples/csharp-net48-rpc-client/DeviceClient.cs`](../examples/csharp-net48-rpc-client/DeviceClient.cs) — C# .NET 4.8 клиент
- [`app-service/core/topologys/fs_depends.py`](../app-service/core/topologys/fs_depends.py) — серверная функция `corr_id_getter_dep`
