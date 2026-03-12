# Документация API: Управление IoT-устройствами

> **Версия:** 1.2  
> **Дата:** 2026  
> **Автор:** Oleg_  
> **Базовый URL:** `{base_url}/api/v1/device-tasks`  

---

## 📝 Общее описание
>- API предназначено для интеграции приложений и веб-сервисов с распределенной сетью IoT-устройств
>- Основной функционал — удаленная инициация команд, загрузка данных и управление задачами на IoT-устройствах
>- Для приложений и веб-сервисов реализован протокол HTTPS+JSON
>- Для безопасного взаимодействие между приложениями используются ограничения по IP, токены доступа JWT (или постоянные токены api-key)
>- Нагруженные проекты могут быть интегрированы прямым подключением к RabbitMQ.

## 📝 Под капотом сервиса
>- PKI для устройств с использованием сертификатов, DI-изолированные пользователи и группы (организации), системная шина и очереди с приоритезацией, а также механизмы TTL
>- Для обмена на нижнем уровне (с устройствами) используется асинхронный RPC-протокол поверх защищенного (mutual TLS) MQTT v5
>- Шина устройств использует сильный ACL на базе сертификатов и определения инфраструктурно-строгих политик маршрутизации сообщений
>- Внутренний сигнальный MQTT-протокол для надежного двунаправленного обмена
>- Дублированная стратегия протокола (push & pull) позволяет управлять устройствами даже в условиях плохой связи и нестабильной сети.
---

### 🔑 Ключевые особенности АПИ
>- `touch_task` — немедленная инициация задачи
>- Поллинг статуса через `GET /{id}`
>- Опциональное оповещение через [**вебхуки (click)**](https://github.com/OlegLebedevRU/iot-rpc-rest-app/blob/master/docs/webhooks.md)
>- Поддержка JSON-полезной нагрузки напрямую в/от устройств
>- TTL устанавливает срок жизни команды, позволяя удерживать в очереди задачи загрузки важных конфигураций/данных; также и противоположно — автоматически отменять в очереди задачи для неактивных устройств
>- Приоритезация (priority) дает возможность обойти загруженную очередь и поставить в топ срочную команду.

---

## Жизненный цикл задачи
````mermaid 
    graph TB
        A[Клиент] -->|POST /| B(touch_task)
        B --> C[Создание задачи]
        C --> D[New task, state=READY]
        D -->|Polling| E["GET /{id}"]
        D -->|Webhook| F[msg-task-result]
        E --> G[on_message]
        F --> G
        G -->|completed/failed| H[Получение результата]
````

---

## ⚙️ Методы API

### `POST /` — Инициация задачи (`touch_task`)

Создает новую задачу и возвращает уникальный `id`. Задача становится доступной для устройства через MQTT.

**Запрос:**
````http 
POST /api/v1/device-tasks/ Content-Type: application/json
````
````json 
{ "ext_task_id": "task-001", "device_id": 4619, "method_code": 20, "priority": 1, "ttl": 5, "payload": { "dt": [ { "mt": 0 } ] } }
````

**Ответ (200 OK):**
````json 
{ "id": "a1b2c3d4-e5f6-7890-g1h2-i3j4k5l6m7n8", "created_at": 1712345678 }
````

> 💡 После вызова `touch_task` устройство получит задачу при следующем поллинге или триггере.

---

### `GET /{id}` — Получение статуса и результата задачи

Позволяет отслеживать состояние задачи. Рекомендуется использовать с экспоненциальной задержкой (polling).

**Запрос:**
````http 
GET /api/v1/device-tasks/a1b2c3d4-e5f6-7890-g1h2-i3j4k5l6m7n8
````

**Ответ (200 OK, выполнена):**
````json 
 {
    "id": "5c75b4ed-2488-4769-b23a-2afae64ea22d",
    "created_at": 1773089559,
    "header": {
        "ext_task_id": "wwhdtkuwgzihwlvi2ule",
        "device_id": 4619,
        "method_code": 20,
        "priority": 0,
        "ttl": 1
    },
    "status": 3,
    "pending_at": 1773089560,
    "locked_at": 1773089560,
    "results": [
       {
            "id": 291,
            "ext_id": 77,
            "status_code": 206,
            "result": {"data": "IoT data from device"}
        } ,
      {
            "id": 292,
            "ext_id": 77,
            "status_code": 200,
            "result": {"status": "OK"}
        }
    ]
}
````

**Ответ (200 OK, в процессе):**
````json 
{ "id": "...", "status": 2, "pending_at": 1712345680, "results": [] }
````

---

### `GET /` — Поиск задач по device_id

Пагинированный список задач для указанного устройства (не включает тело параметров и список результатов).

**Запрос:**
````http 
GET /api/v1/device-tasks/?device_id=4619&page=1&size=10
````

**Ответ:**
````json 
{ "items": [ { "id": "a1b2c3d4-e5f6-...", "ext_task_id": "task-001", "device_id": 4619, "method_code": 20, "priority": 1, "ttl": 5, "status": 4, "created_at": "2025-02-05T12:34:56", "pending_at": "2025-02-05T12:35:00", "locked_at": "2025-02-05T12:35:02", "org_id": 101 } ], "page": 1, "size": 10, "total": 1, "pages": 1 }
````

---

### `DELETE /{id}` — Мягкое удаление задачи

Помечает задачу как удалённую. Не влияет на уже отправленные команды.
````http 
DELETE /api/v1/device-tasks/a1b2c3d4-e5f6-...
````

**Ответ:**
````json
 { "id": "a1b2c3d4-e5f6-...", "deleted_at": 1712345700 }
````

---

## 📤 Вебхуки (Webhooks) — альтернатива поллингу

Рекомендуется для высоконагруженных систем вместо частого polling.

### Поддерживаемые события:

| `event_type` | Описание |
|--------------|---------|
| `msg-task-result` | Выполнение задачи завершено (статус `completed` или `failed`) |
| `msg-event` | Асинхронное событие от устройства (например, keep-alive) |

---

### Установка вебхука
````http 
PUT /api/v1/webhooks/msg-task-result Content-Type: application/json
````

**Ответ:**
````json 
{ "org_id": 101, "event_type": "msg-task-result", "url": "https://your-service.com/hooks/task-result", "headers": { "Authorization": "Bearer xxx" }, "is_active": true, "created_at": 1712345678, "updated_at": 1712345678 }
````

---

### Формат вебхука `msg-task-result`
````http 
POST https://your-webhook-url.com/hooks/task-result/fddf6675-42d3-478a-b81c-3abfc7ed84e0
    Content-Type: application/json
    X-Msg-Type: msg-task-result
    X-Ext-Id: 12345
    X-Result-Id: 304
    X-Status-Code: 200
    X-Signature: sha256=... (пример кастомного header - опционально, если установлен при регистрации вебхука)
 
````
````json 
{ 

    "result": {
        "data": "IoT data from device"
    }
}
````

---

## 📝 Поддерживаемые методы и форматы

Формат полезной нагрузки (`payload.dt`) полностью совместим с устаревшим `cmdToDevice`.

### Примеры запросов

#### Запрос HELLO-пакета
````json
 { "ext_task_id": "cells-list", "device_id": 4619, "method_code": 20, "payload": { "dt": [ { "mt": 0 } ] } }
````

#### Получение списка ячеек
````json 
{ "ext_task_id": "cells-list", "device_id": 4619, "method_code": 20, "payload": { "dt": [ { "mt": 4 } ] } }
````

#### Привязка пинкода к ячейке
````json 
{ "ext_task_id": "bind-pin", "device_id": 4619, "method_code": 16, "payload": { "dt": [ { "cd": "123456", "cl": 1 } ] } }
````

#### Перезагрузка контроллера
````json 
{ "ext_task_id": "reboot-4619", "device_id": 4619, "method_code": 21, "payload": { "dt": [] } }
````

#### Удаление всех идентификаторов
````json
 { "ext_task_id": "wipe-cards", "device_id": 4619, "method_code": 26, "payload": { "dt": ["*"] } }
````

---

## 📚 Статусы задач

| Код | Название    | Описание                     |
|-----|-------------|------------------------------|
| `0` | ready (new) | Задача создана               |
| `1` | pending     | Устройство запросило задачу  |
| `2` | locked      | Устройство начало выполнение |
| `3` | completed   | Успешно выполнена            |
| `4` | expired     | Просрочена (истек TTL)       |
| `5` | deleted     | Удалена АПИ-клиентом         |
| `6` | failed      | Ошибка выполнения            |
| `7` | undefined   | Непонятная проблема          |

---

## 🌐 Интеграция с MQTT/AMQP

API на внутренней шине интегрировано с MQTT v5 и AMQP:

1. `touch_task` → генерирует `correlation_data = UUID4(task.id)`
2. Устройство получает `correlation_data` через `dev/<SN>/req` или `srv/<SN>/tsk`
3. Все этапы RPC используют этот `correlation_data`
4. Результат (`res`) сохраняется и доступен через `GET /{id}` или вебхук.

---

## 📄 Пример полного workflow

### Шаг 1: Создать задачу
````bash 
curl -X POST https://dev.leo4.ru/api/v1/device-tasks
-H "x-api-key: xxx"
-H "Content-Type: application/json"
-d '{ "ext_task_id": "hello-001", "device_id": 4619, "method_code": 20, "payload": {"dt": [{"mt": 0}]} }'
````

### Шаг 2: Ожидание результата (вариант 1 — polling)
````python 
import time 
import requests
task_id = "a1b2c3d4-e5f6-..." 
while True: 
    resp = requests.get(f"https://dev.leo4.ru/api/v1/device-tasks/{task_id}") 
    data = resp.json() 
    if data["status"] in [3, 4, 5, 6, 7]: 
        print("Result:", data["results"]) 
        break 
    time.sleep(2)
````

### Шаг 2: Ожидание результата (вариант 2 — webhook)
````python
#Установите вебхук один раз
requests.put( "https://dev.leo4.ru/api/v1/webhooks/msg-task-result", json={"url": "your.app/hook"} )
#Ваш сервер получит результат автоматически
````

---

## 🔐 Безопасность

- Все запросы авторизуются, требуя `x-api-key: ApiKey <key>`, JWT или сертификат АПИ-клиента 
- `org_id` извлекается из данных авторизации и используется для сквозной изоляции ресурсов
- HTTPS обязательно
- Webhook-запросы могут содержать кастомные `headers` для авторизации (опционально)

---

## Контакты

По вопросам интеграции:  
📧 info@platerra.ru  
📞 +7 (9I6) 206-7I-24  
🌐 https://platerra.ru

> © 2026 Leo4. Все права защищены.  
> Версия документа: 1.2