# Internal API Contract v1 (Межсервисный протокол взаимодействия)

Данный документ описывает контракт взаимодействия внутренних сервисов экосистемы (включая `etranprocessing`, `MenuBuilder`, биллинг-воркеры и инженерные консоли) с сервисом ядра платформы Leo4 (`app1`).

---

## 1. Архитектура и сетевая изоляция

В рамках архитектуры строгого разделения:
* **Public B2B API** доступен по префиксу `/api/v1/*` через внешний Nginx (`https://dev.leo4.ru/api/v1/`). Авторизация выполняется исключительно по ключам организаций (`x-api-key`). Включает только разделы: `Device tasks`, `Device events`, `Devices`, `Gauges`, `Webhooks`.
* **Internal Control Plane API** доступен по префиксу `/api/internal/v1/*` **только внутри закрытой Docker-сети** проекта (`http://app1:8000/api/internal/v1/...`).
* **Защита периметра**: Внешний Nginx блокирует любые входящие запросы к `/api/internal/*` с кодом `403 Forbidden`, а также сбрасывает любые входящие служебные заголовки `X-Internal-Service-Key` и `X-Org-Id` на публичных маршрутах.

---

## 2. Стандарты аутентификации и контекста

При каждом вызове внутреннего API смежный сервис обязан передавать следующие HTTP-заголовки:

| Заголовок | Тип | Обязательность | Описание |
|---|---|---|---|
| `X-Internal-Service-Key` | String | **Обязательно** | Секретный ключ сервиса (соответствует значению `APP_CONFIG__AUTH__INTERNAL_SERVICE_KEY` в `.env`). Также поддерживается формат `Authorization: Bearer <secret>`. |
| `X-Org-Id` | Integer | Обязательно для tenant-запросов | Идентификатор организации, от имени которой выполняется операция. (Также поддерживается `?org_id=<id>` в query). |
| `Content-Type` | String | Для POST/PUT | `application/json` |

---

## 3. Каталог маршрутов Internal API

### 3.1. Управление устройствами и реестром (`/api/internal/v1/devices`)
* `GET /api/internal/v1/devices/?device_id=<id>` — Получение реестра устройств целевой организации (`X-Org-Id`).
* `PUT /api/internal/v1/devices/{device_id}` — Добавление/обновление тегов устройства (location, zone и т.п.).

### 3.2. Задачи и команды устройствам (`/api/internal/v1/device-tasks`)
* `POST /api/internal/v1/device-tasks/` — Создание задачи/команды для устройства (body: `TaskCreate`).
* `GET /api/internal/v1/device-tasks/{id}` — Получение статуса и полного результата выполнения задачи по UUID.
* `GET /api/internal/v1/device-tasks/?device_id=<id>` — Пагинированный список задач устройства.
* `DELETE /api/internal/v1/device-tasks/{id}` — Мягкое удаление задачи.

### 3.3. Телеметрия и события (`/api/internal/v1/device-events`)
* `GET /api/internal/v1/device-events/?device_id=<id>` — Пагинированная выборка событий устройства.
* `GET /api/internal/v1/device-events/incremental?device_id=<id>&last_id=<id>` — Строго инкрементальная выборка новых событий.
* `GET /api/internal/v1/device-events/fields/?device_id=<id>&event_type_code=<code>&tag=<tag>` — Выборка и агрегация полей событий (например, polling датчиков).

### 3.4. Показания датчиков (`/api/internal/v1/gauges`)
* `GET /api/internal/v1/gauges/?device_id=<id>&type=<type>` — Пагинированный список показаний датчиков организации.

### 3.5. Вебхуки (`/api/internal/v1/webhooks`)
* `GET /api/internal/v1/webhooks/` — Список всех настроенных вебхуков организации.
* `POST /api/internal/v1/webhooks/` — Создание нового вебхука организации.
* `PUT /api/internal/v1/webhooks/{event_type}` — Создание или обновление вебхука для типа события (`msg-event`, `msg-task-result`).
* `DELETE /api/internal/v1/webhooks/{event_type}` — Удаление вебхука по типу события.

### 3.6. Провиженинг и учетные записи (`/api/internal/v1/provisioning`)
* `POST /api/internal/v1/provisioning/terminals` — Провиженинг одиночного терминала в БД и RabbitMQ.
* `POST /api/internal/v1/provisioning/terminals/batch` — Пакетный провиженинг терминалов.
* `POST /api/internal/v1/provisioning/terminals/status` — Проверка статуса регистрации и связи устройств.
* `POST /api/internal/v1/provisioning/api-keys` — Создание или обновление API-ключа организации.
* `GET /api/internal/v1/provisioning/api-keys/{org_id}` — Получение API-ключа организации (параметр `?mask=true`).
* `DELETE /api/internal/v1/provisioning/api-keys/{org_id}` — Удаление/отзыв API-ключа организации.

### 3.7. Управление биллингом (`/api/internal/v1/billing`)
* `GET /api/internal/v1/billing/coefficients` — Получение действующих коэффициентов биллинга.
* `PUT /api/internal/v1/billing/coefficients` — Установка тарифных коэффициентов.
* `GET /api/internal/v1/billing/consumption?target_org_id=<id>&period=YYYY-MM-01` — Запрос потребления организации за месяц.
* `GET /api/internal/v1/billing/consumption/history?target_org_id=<id>` — История потребления организации.
* `POST /api/internal/v1/billing/recalculate` — Принудительный перерасчет биллинга за период.

### 3.8. Инженерная диагностика и Live Logs (`/api/internal/v1/diagnostics`)
* `WebSocket /api/internal/v1/diagnostics/ws/devices/{sn}` — Двусторонний сокет для live-логов и команд (`START_LOG`, `STOP_LOG`, `EXEC`, `CANCEL`). Требует заголовки суперпользователя (`X-Role: superuser`, `X-Org-Id: <id>`).

### 3.9. Системный администратор (`/api/internal/v1/admin`)
* `POST /api/internal/v1/admin/?action=get_d` — Репликация реестра устройств.
* `POST /api/internal/v1/admin/?action=get_u` — Репликация определений пользователей RabbitMQ.

---

## 4. Примеры вызовов из смежных сервисов

### 4.1. Создание задачи для устройства (через внутренний API)
```bash
curl -X POST "http://app1:8000/api/internal/v1/device-tasks/" \
     -H "X-Internal-Service-Key: <APP_CONFIG__AUTH__INTERNAL_SERVICE_KEY>" \
     -H "X-Org-Id: 12" \
     -H "Content-Type: application/json" \
     -d '{
       "device_id": 773,
       "method_code": 1,
       "params": {"action": "open_door", "channel": 1}
     }'
```

### 4.2. Провиженинг API-ключа для организации
```bash
curl -X POST "http://app1:8000/api/internal/v1/provisioning/api-keys" \
     -H "X-Internal-Service-Key: <APP_CONFIG__AUTH__INTERNAL_SERVICE_KEY>" \
     -H "Content-Type: application/json" \
     -d '{
       "org_id": 12,
       "api_key": "leo4_sec_custom_org12_key",
       "name": "Production Partner Key",
       "is_active": true
     }'
```

### 4.3. Пример на Python (`httpx.AsyncClient`)
```python
import httpx

INTERNAL_API_BASE = "http://app1:8000/api/internal/v1"
INTERNAL_SECRET = "your_configured_internal_service_key"

async def send_command_to_device(org_id: int, device_id: int, method_code: int, params: dict):
    headers = {
        "X-Internal-Service-Key": INTERNAL_SECRET,
        "X-Org-Id": str(org_id),
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(base_url=INTERNAL_API_BASE) as client:
        response = await client.post(
            "/device-tasks/",
            headers=headers,
            json={
                "device_id": device_id,
                "method_code": method_code,
                "params": params,
            },
        )
        response.raise_for_status()
        return response.json()
```
