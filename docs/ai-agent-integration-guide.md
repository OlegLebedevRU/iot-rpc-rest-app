# Практическое руководство: Интеграция AI-агента с LEO4 API

> **Версия:** 1.0  
> **Дата:** 2026-04-04  
> **Платформа:** dev.leo4.ru  
> **Контакты:** info@platerra.ru | https://platerra.ru

---

## Введение

Данное руководство описывает, как практически подключить AI-агента (LLM с Function Calling, MCP-сервер, чат-бот) к REST API платформы LEO4, чтобы по текстовой или голосовой команде пользователя выполнялись действия на IoT-устройствах.

**Итоговый сценарий:**

```
Пользователь: "Открой ячейку 5"
AI-агент    → POST /device-tasks/ {method_code: 51, payload: {dt: [{cl: 5}]}}
            → GET /device-tasks/{id} → status: DONE
AI-агент    → "Ячейка 5 открыта ✅"
```

### Общая схема потока данных

```
┌──────────────┐     ┌──────────────────┐     ┌───────────────┐     ┌──────────────┐
│  Пользователь │     │    AI-агент       │     │  LEO4 REST API │     │  Устройство  │
│  (чат/голос)  │     │  (LLM + Tools)   │     │  dev.leo4.ru   │     │  (ESP32)     │
└──────┬───────┘     └────────┬─────────┘     └───────┬───────┘     └──────┬───────┘
       │ "Открой ячейку 5"   │                        │                     │
       │────────────────────>│                        │                     │
       │                     │ POST /device-tasks/    │                     │
       │                     │ x-api-key: ApiKey xxx  │                     │
       │                     │ {method_code:51, ...}  │                     │
       │                     │───────────────────────>│                     │
       │                     │                        │ MQTT RPC            │
       │                     │                        │ TSK→REQ→RSP→RES→CMT│
       │                     │                        │────────────────────>│
       │                     │                        │<────────────────────│
       │                     │ GET /device-tasks/{id} │  status=200         │
       │                     │───────────────────────>│                     │
       │                     │  {status:3, DONE}      │                     │
       │                     │<───────────────────────│                     │
       │ "Ячейка 5 открыта ✅"│                        │                     │
       │<────────────────────│                        │                     │
```

---

## Быстрый старт (чек-лист)

1. **Получите API-ключ** в личном кабинете (dev.leo4.ru) — он привязан к вашей организации
2. **Узнайте `device_id`** целевого устройства (виден в ЛК → левая панель → Номер связи)
3. **Проверьте связь** — отправьте hello-запрос (см. раздел ниже)
4. **Подключите LLM** с Function Calling (см. раздел «Полный пример AI-агента»)
5. **Для продакшена** — настройте вебхуки вместо polling (см. раздел «Webhook»)

---

## Проверка связи (curl)

```bash
curl -X POST https://dev.leo4.ru/api/v1/device-tasks/ \
  -H "x-api-key: ApiKey ВАШ_КЛЮЧ" \
  -H "Content-Type: application/json" \
  -d '{
    "ext_task_id": "test-hello-001",
    "device_id": 4619,
    "method_code": 20,
    "ttl": 5,
    "payload": {"dt": [{"mt": 0}]}
  }'
```

**Ожидаемый ответ:**

```json
{
  "id": "a1b2c3d4-e5f6-7890-g1h2-i3j4k5l6m7n8",
  "created_at": 1712345678
}
```

---

## Структура HTTP-запроса к LEO4 API

### Эндпоинт

```
POST https://dev.leo4.ru/api/v1/device-tasks/
```

### Заголовки

| Заголовок | Значение | Описание |
|-----------|----------|----------|
| `Content-Type` | `application/json` | Формат тела запроса |
| `x-api-key` | `ApiKey ваш-секретный-ключ` | API-ключ организации |

> ⚠️ Без заголовка `x-api-key` сервер вернёт `401 Unauthorized`.

### Поля тела запроса

| Поле | Тип | Обязательное | По умолчанию | Описание |
|------|-----|:---:|:---:|----------|
| `ext_task_id` | string | ✅ | — | Ваш внешний идентификатор (для идемпотентности) |
| `device_id` | int | ✅ | — | ID устройства в системе LEO4 |
| `method_code` | int (0–65534) | ✅ | 20 | Код команды |
| `priority` | int (0–9) | — | 0 | Приоритет задачи в очереди |
| `ttl` | int (0–44639) | — | 1 | Время жизни задачи в минутах |
| `payload` | object | — | null | Параметры команды в формате `{\"dt\": [...]}` |

### Основные коды команд (method_code)

| Код | Команда | Пример payload |
|-----|---------|----------------|
| 20 | Короткая команда (hello) | `{\"dt\": [{\"mt\": 0}]}` |
| 20 | Список ячеек | `{\"dt\": [{\"mt\": 4}]}` |
| 21 | Перезагрузка | `{\"dt\": [{\"mt\": 0}]}` |
| 51 | Открыть ячейку N | `{\"dt\": [{\"cl\": N}]}` |
| 16 | Привязка карты/пинкода | `{\"dt\": [{\"cl\": N, \"cd\": \"...\"}]}` |
| 49 | Запись в NVS | `{\"dt\": [{\"ns\": \"...\", \"k\": \"...\", \"v\": \"...\", \"t\": \"...\"}]}` |
| 50 | Чтение NVS | `{\"dt\": [{\"ns\": \"...\", \"k\": \"...\"}]}` |

### Статусы задач

| Код | Состояние | Описание |
|-----|-----------|----------|
| 0 | READY | Задача создана, ожидает устройство |
| 1 | PENDING | Устройство подтвердило получение |
| 2 | LOCK | Устройство выполняет задачу |
| 3 | DONE | Успешно выполнена |
| 4 | EXPIRED | TTL истёк |
| 5 | DELETED | Удалена через API |
| 6 | FAILED | Ошибка выполнения |

---

## 1. Полный пример AI-агента (Python)

Зависимости:

```bash
pip install openai httpx
```

### Код агента

```python
"""
AI-агент: чат-сообщение → POST /device-tasks/ → результат пользователю
Зависимости: pip install openai httpx
"""
import httpx
import json
from openai import OpenAI

# ── Конфигурация ──
LEO4_API_URL = "https://dev.leo4.ru/api/v1"
LEO4_API_KEY = "ApiKey ВАШ_КЛЮЧ"          # x-api-key из ЛК LEO4
DEVICE_ID    = 4619                         # ID целевого устройства
OPENAI_KEY   = "sk-..."                     # Ключ OpenAI (или другой LLM)

client = OpenAI(api_key=OPENAI_KEY)

# ── Tool-описание для LLM (Function Calling) ──
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_device_task",
            "description": "Отправить команду IoT-устройству через LEO4 API",
            "parameters": {
                "type": "object",
                "properties": {
                    "method_code": {
                        "type": "integer",
                        "description": (
                            "Код команды: 51=открыть ячейку, "
                            "20=короткая команда, 21=перезагрузка"
                        )
                    },
                    "payload": {
                        "type": "object",
                        "description": (
                            'Параметры команды, например '
                            '{"dt": [{"cl": 5}]} для открытия ячейки 5'
                        )
                    },
                    "ttl": {
                        "type": "integer",
                        "description": "Время жизни задачи в минутах (по умолчанию 5)"
                    }
                },
                "required": ["method_code", "payload"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_task_status",
            "description": "Проверить статус выполнения задачи на устройстве",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "UUID задачи, полученный при создании"
                    }
                },
                "required": ["task_id"]
            }
        }
    }
]


# ── Функции взаимодействия с LEO4 API ──

def create_device_task(method_code: int, payload: dict, ttl: int = 5) -> dict:
    """POST /api/v1/device-tasks/ — создание задачи для устройства."""
    with httpx.Client() as http:
        response = http.post(
            f"{LEO4_API_URL}/device-tasks/",
            headers={
                "Content-Type": "application/json",
                "x-api-key": LEO4_API_KEY,
            },
            json={
                "ext_task_id": f"chat-{method_code}-auto",
                "device_id": DEVICE_ID,
                "method_code": method_code,
                "priority": 1,
                "ttl": ttl,
                "payload": payload,
            },
        )
        response.raise_for_status()
        return response.json()  # {"id": "uuid...", "created_at": 1712345678}


def get_task_status(task_id: str) -> dict:
    """GET /api/v1/device-tasks/{id} — получение статуса задачи."""
    with httpx.Client() as http:
        response = http.get(
            f"{LEO4_API_URL}/device-tasks/{task_id}",
            headers={"x-api-key": LEO4_API_KEY},
        )
        response.raise_for_status()
        return response.json()


# ── Маршрутизатор tool-вызовов ──

TOOL_DISPATCH = {
    "create_device_task": create_device_task,
    "get_task_status": get_task_status,
}


def execute_tool(tool_name: str, arguments: dict) -> dict:
    """Выполнить tool-вызов по имени."""
    func = TOOL_DISPATCH[tool_name]
    return func(**arguments)


# ── Основной цикл чат-агента ──

def chat(user_message: str) -> str:
    """Обработка сообщения пользователя через LLM с Function Calling."""
    messages = [
        {
            "role": "system",
            "content": (
                "Ты — AI-ассистент для управления IoT-устройствами "
                "через платформу LEO4. "
                "Когда пользователь просит выполнить действие с устройством, "
                "используй create_device_task. "
                "Коды команд: 51 — открыть ячейку "
                '(payload: {"dt": [{"cl": N}]}), '
                "20 — короткая команда (mt=0 — hello, mt=4 — список ячеек), "
                "21 — перезагрузка. "
                "После создания задачи проверь её статус через get_task_status."
            ),
        },
        {"role": "user", "content": user_message},
    ]

    # Шаг 1: LLM решает, нужен ли tool-вызов
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        tools=TOOLS,
    )

    msg = response.choices[0].message

    # Шаг 2: Если LLM запросил tool — выполняем
    while msg.tool_calls:
        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)

            print(f"  🔧 Вызов: {name}({args})")
            result = execute_tool(name, args)
            print(f"  ✅ Результат: {result}")

            messages.append(msg)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

        # Шаг 3: LLM формирует ответ пользователю
        # (или вызывает ещё один tool)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=TOOLS,
        )
        msg = response.choices[0].message

    return msg.content


# ── Запуск ──
if __name__ == "__main__":
    while True:
        user_input = input("\n💬 Вы: ")
        if user_input.lower() in ("exit", "quit"):
            break
        answer = chat(user_input)
        print(f"🤖 Агент: {answer}")
```

### Пример диалога

```
💬 Вы: Открой ячейку 5
  🔧 Вызов: create_device_task({"method_code": 51, "payload": {"dt": [{"cl": 5}]}, "ttl": 5})
  ✅ Результат: {"id": "a1b2c3d4-...", "created_at": 1712345678}
  🔧 Вызов: get_task_status({"task_id": "a1b2c3d4-..."})
  ✅ Результат: {"status": 3, "results": [{"status_code": 200, ...}]}
🤖 Агент: Ячейка 5 успешно открыта ✅

💬 Вы: Перезагрузи устройство
  🔧 Вызов: create_device_task({"method_code": 21, "payload": {"dt": [{"mt": 0}]}, "ttl": 5})
  ✅ Результат: {"id": "b2c3d4e5-...", "created_at": 1712345700}
🤖 Агент: Команда на перезагрузку отправлена. Устройство перезагрузится в течение минуты.

💬 Вы: Какие ячейки есть?
  🔧 Вызов: create_device_task({"method_code": 20, "payload": {"dt": [{"mt": 4}]}, "ttl": 5})
  ✅ Результат: {"id": "c3d4e5f6-...", "created_at": 1712345720}
  🔧 Вызов: get_task_status({"task_id": "c3d4e5f6-..."})
  ✅ Результат: {"status": 3, "results": [{"status_code": 200, "result": {...}}]}
🤖 Агент: На устройстве доступны ячейки 1–12. Все в рабочем состоянии.
```

---

## 2. Получение результата: Polling vs Webhook

### Вариант A — Polling (простой)

Подходит для отладки и простых сценариев:

```python
import time
import httpx

def wait_for_result(task_id: str, timeout: int = 30) -> dict:
    """Ожидание результата задачи с polling."""
    headers = {"x-api-key": "ApiKey ВАШ_КЛЮЧ"}
    deadline = time.time() + timeout

    while time.time() < deadline:
        resp = httpx.get(
            f"https://dev.leo4.ru/api/v1/device-tasks/{{task_id}}",
            headers=headers,
        )
        data = resp.json()
        # статус >= 3 означает финальное состояние:
        # 3=DONE, 4=EXPIRED, 5=DELETED, 6=FAILED
        if data["status"] >= 3:
            return data
        time.sleep(2)

    raise TimeoutError(f"Задача {{task_id}} не завершилась за {{timeout}}с")


# Использование:
# task = create_device_task(method_code=51, payload={"dt": [{"cl": 5}]})
# result = wait_for_result(task["id"])
# print(f"Статус: {{result['status']}}, Результаты: {{result['results']}}")
```

### Вариант B — Webhook (рекомендуется для продакшена)

#### Шаг 1: Регистрация вебхука (один раз)

```python
import httpx

httpx.put(
    "https://dev.leo4.ru/api/v1/webhooks/msg-task-result",
    headers={
        "x-api-key": "ApiKey ВАШ_КЛЮЧ",
        "Content-Type": "application/json",
    },
    json={
        "url": "https://your-ai-agent.com/hooks/task-result",
        "headers": {"Authorization": "Bearer ваш-токен"},
        "is_active": True,
    },
)
```

#### Шаг 2: Приём вебхуков на стороне AI-агента

```python
from fastapi import FastAPI, Request

app = FastAPI()

@app.post("/hooks/task-result")
async def handle_task_result(request: Request):
    """Обработка входящего вебхука от LEO4."""
    device_id   = request.headers.get("X-Device-Id")
    status_code = request.headers.get("X-Status-Code")
    ext_id      = request.headers.get("X-Ext-Id")
    result_id   = request.headers.get("X-Result-Id")
    body = await request.json()

    print(f"Устройство {{device_id}}: статус={{status_code}}, ext_id={{ext_id}}")
    print(f"Результат: {{body}}")

    # Здесь AI-агент может:
    # - сформировать ответ пользователю в чат
    # - запустить следующий шаг сценария (каскадная оркестрация)
    # - записать результат в лог / БД
    return {"ok": True}
```

#### Заголовки входящего вебхука

| Заголовок | Описание |
|-----------|----------|
| `X-Device-Id` | ID устройства |
| `X-Status-Code` | Код статуса выполнения |
| `X-Ext-Id` | Внешний идентификатор задачи (`ext_task_id`) |
| `X-Result-Id` | ID результата |

#### Типы вебхуков

| Тип события | Описание |
|------------|----------|
| `msg-task-result` | Результат выполнения задачи (ответ на команду) |
| `msg-event` | Асинхронное событие от устройства (телеметрия, NFC, и т.д.) |

---

## 3. Интеграция через MCP (Model Context Protocol)

Для LLM с поддержкой MCP (Claude, GPT и др.) API LEO4 описывается как набор tools:

```json
{
  "tools": [
    {
      "name": "create_device_task",
      "description": "Создать задачу (команду) для IoT-устройства через LEO4",
      "inputSchema": {
        "type": "object",
        "properties": {
          "device_id":   { "type": "integer", "description": "ID устройства" },
          "method_code": { "type": "integer", "description": "Код команды (51=открыть, 20=короткая, 21=reboot)" },
          "payload":     { "type": "object",  "description": "Параметры: {\"dt\": [{\"cl\": 5}]}" },
          "ttl":         { "type": "integer", "description": "TTL в минутах", "default": 5 }
        },
        "required": ["device_id", "method_code", "payload"]
      }
    },
    {
      "name": "get_task_status",
      "description": "Получить статус задачи по UUID",
      "inputSchema": {
        "type": "object",
        "properties": {
          "task_id": { "type": "string", "description": "UUID задачи" }
        },
        "required": ["task_id"]
      }
    },
    {
      "name": "list_device_events",
      "description": "Получить список событий устройства",
      "inputSchema": {
        "type": "object",
        "properties": {
          "device_id": { "type": "integer", "description": "ID устройства" }
        },
        "required": ["device_id"]
      }
    },
    {
      "name": "get_telemetry",
      "description": "Получить временные ряды телеметрии устройства",
      "inputSchema": {
        "type": "object",
        "properties": {
          "device_id": { "type": "integer", "description": "ID устройства" }
        },
        "required": ["device_id"]
      }
    },
    {
      "name": "configure_webhook",
      "description": "Настроить вебхук для получения событий/результатов",
      "inputSchema": {
        "type": "object",
        "properties": {
          "event_type": { "type": "string", "enum": ["msg-event", "msg-task-result"] },
          "url":        { "type": "string", "description": "URL вашего сервера" },
          "headers":    { "type": "object", "description": "Дополнительные заголовки" },
          "is_active":  { "type": "boolean", "default": true }
        },
        "required": ["event_type", "url"]
      }
    }
  ]
}
```

### Маппинг MCP Tool → LEO4 API

| MCP Tool | HTTP-метод | LEO4 API Endpoint |
|----------|------------|-------------------|
| `create_device_task` | `POST` | `/api/v1/device-tasks/` |
| `get_task_status` | `GET` | `/api/v1/device-tasks/{id}` |
| `list_device_events` | `GET` | `/api/v1/device-events/` |
| `get_telemetry` | `GET` | `/api/v1/device-events/fields/` |
| `configure_webhook` | `PUT` | `/api/v1/webhooks/{event_type}` |

> Любой MCP-сервер или LLM с поддержкой Function Calling может быть подключён к LEO4 через описание этих эндпоинтов как инструментов.

---

## 4. Продвинутые сценарии

### Каскадная оркестрация (Closed-Loop)

AI-агент получает событие через вебхук и автоматически реагирует:

```python
@app.post("/hooks/device-event")
async def handle_device_event(request: Request):
    """Автономный контур: событие → анализ → действие."""
    body = await request.json()
    event_code = body.get("200")  # код типа события
    params = body.get("300", [])  # параметры

    # Пример: температура превысила порог
    if event_code == 44:  # DevHealthCheck
        temperature = extract_temperature(params)
        if temperature and temperature > 85:
            # AI-агент автоматически отправляет команду
            create_device_task(
                method_code=20,
                payload={"dt": [{"mt": 7}]},  # снизить мощность
                ttl=2,
            )
            notify_operator(
                f"⚠️ Температура {{temperature}}°C — команда отправлена"
            )

    return {"ok": True}
```

### Параллельная массовая активация

Отправка команд на множество устройств одновременно:

```python
import asyncio
import httpx

async def mass_activate(
    device_ids: list[int],
    method_code: int,
    payload: dict,
):
    """Параллельная отправка задач на N устройств."""
    async with httpx.AsyncClient() as http:
        tasks = [
            http.post(
                f"{LEO4_API_URL}/device-tasks/",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": LEO4_API_KEY,
                },
                json={
                    "ext_task_id": f"mass-{device_id}-{method_code}",
                    "device_id": device_id,
                    "method_code": method_code,
                    "priority": 1,
                    "ttl": 5,
                    "payload": payload,
                },
            )
            for device_id in device_ids
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    success = sum(
        1 for r in results
        if not isinstance(r, Exception) and r.status_code == 200
    )
    failed = len(device_ids) - success
    print(f"Отправлено: {{len(device_ids)}}, Успешно: {{success}}, Ошибок: {{failed}}")
    return results


# Использование:
# asyncio.run(mass_activate(
#     [4619, 4620, 4621],
#     method_code=51,
#     payload={"dt": [{"cl": 1}]},
# ))
```

---

## 5. Безопасность

- Все запросы требуют заголовок `x-api-key: ApiKey <ключ>`
- `org_id` извлекается из API-ключа автоматически — данные изолированы по организации
- HTTPS обязательно для всех вызовов
- Webhook-запросы могут содержать кастомные `headers` для авторизации на вашей стороне
- Каждый API-ключ даёт доступ только к устройствам своей организации

---

## Связанные документы

- [Презентация решения LEO4](./solution-presentation.md)
- [Workflow задач (Task Workflow)](./1-task-workflow-doc.md)
- [Документация по вебхукам](./3-webhooks.md)
- [Формат событий устройств](./2-device-events-doc.md)

---

> © 2026 Leo4 / Platerra. Все права защищены.  
> Контакты: info@platerra.ru | +7 (916) 206-71-24 | https://platerra.ru