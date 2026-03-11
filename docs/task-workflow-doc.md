# Документация API: Управление задачами для IoT-устройств

> **Версия:** 1.2  
> **Дата:** 2025  
> **Автор:** GigaCode  
> **Базовый URL:** `{base_url}/api/v1/device-tasks`  

---

## Общее описание

API предназначено для инициации и управления задачами на IoT-устройствах через асинхронный RPC-протокол поверх MQTT v5.

### Ключевые особенности:
- `touch_task` — немедленная инициация задачи
- Поллинг статуса через `GET /{id}`
- Опциональное оповещение через **вебхуки**
- Поддержка JSON-полезной нагрузки с тегами `dt`, совместимыми с устаревшим `cmdToDevice`
- Интеграция с MQTT для двунаправленного обмена

---

## Жизненный цикл задачи
````mermaid 
    graph TB
        A[Клиент] -->|POST /| B(touch_task)
        B --> C[Создание задачи]
        C --> D[Registered callback]
        D -->|Polling| E["GET /{id}"]
        D -->|Webhook| F[msg-task-result]
        E --> G[on_message]
        F --> G
        G -->|completed/failed| H[Получение результата]
````

---

## Методы API

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
  "id": "a1b2c3d4-e5f6-7890-g1h2-i3j4k5l6m7n8", 
  "created_at": 1712345678, 
  "header": { "ext_task_id": "task-001", "device_id": 4619, "method_code": 20, "priority": 1, "ttl": 5 }, 
  "status": 4, 
  "pending_at": 1712345680, 
  "locked_at": 1712345682, 
  "results": [ { "id": 101, "ext_id": 0, "status_code": 200, "result": "{\"200\":0,\"300\":[{\"310\":\"1.04.025\",\"311\":null},{\"310\":\"\",\"311\":13}]}" } ]
}  
````

**Ответ (200 OK, в процессе):**
````json 
{ "id": "...", "status": 2, "pending_at": 1712345680, "results": [] }
````

---

### `GET /` — Поиск задач по device_id

Пагинированный список задач для указанного устройства.

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

## Вебхуки (Webhooks) — альтернатива поллингу

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
POST https://your-webhook-url.com/hooks/task-result Content-Type: application/json X-Signature: sha256=... (опционально)
````
````json 
{ "event_type": "msg-task-result", "timestamp": 1712345690, "data": { "id": "a1b2c3d4-e5f6-7890-g1h2-i3j4k5l6m7n8", "created_at": 1712345678, "header": { "ext_task_id": "task-001", "device_id": 4619, "method_code": 20 }, "status": 4, "results": [ { "id": 101, "ext_id": 0, "status_code": 200, "result": "{"200":0,"300":[{"310":"1.04.025"}]}" } ] } }
````

---

## Поддерживаемые методы и форматы `dt`

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

## Статусы задач

| Код | Название | Описание |
|-----|--------|---------|
| `1` | new | Задача создана |
| `2` | pending | Устройство запросило задачу |
| `3` | locked | Устройство начало выполнение |
| `4` | completed | Успешно выполнена |
| `5` | failed | Ошибка выполнения |

---

## Интеграция с MQTT

API интегрировано с MQTT v5:

1. `touch_task` → генерирует `correlation_data = UUID4(task.id)`
2. Устройство получает `correlation_data` через `dev/<SN>/req` или `srv/<SN>/tsk`
3. Все этапы RPC используют этот `correlation_data`
4. Результат (`res`) сохраняется и доступен через `GET /{id}` или вебхук

---

## Пример полного workflow

### Шаг 1: Создать задачу
````bash 
curl -X POST https://api.example.com/api/v1/device-tasks
-H "Authorization: ApiKey xxx"
-H "Content-Type: application/json"
-d '{ "ext_task_id": "hello-001", "device_id": 4619, "method_code": 20, "payload": {"dt": [{"mt": 0}]} }'
````

### Шаг 2: Ожидание результата (вариант 1 — polling)
````python 
import time 
import requests
task_id = "a1b2c3d4-e5f6-..." 
while True: 
    resp = requests.get(f"https://api.example.com/api/v1/device-tasks/{task_id}") 
    data = resp.json() 
    if data["status"] in [4, 5]: 
        print("Result:", data["results"]) 
        break 
    time.sleep(2)
````

### Шаг 2: Ожидание результата (вариант 2 — webhook)
````python
#Установите вебхук один раз
requests.put( "https://api.example.com/api/v1/webhooks/msg-task-result", json={"url": "your.app/hook"} )
#Ваш сервер получит результат автоматически
````

---

## Безопасность

- Все запросы требуют `Authorization: ApiKey <key>` или JWT
- `org_id` извлекается из ключа и используется для изоляции данных
- HTTPS обязательно
- Webhook-запросы могут подписываться (опционально)

---

## Контакты

По вопросам интеграции:  
📧 info@platerra.ru  
📞 +7 (9I6) 206-7I-24  
🌐 https://platerra.ru

> © 2026 Leo4. Все права защищены.  
> Версия документа: 1.2