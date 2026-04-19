# Сценарии взаимодействия (Sequence)

> **Файл:** `docs/sequence.md`
> **Версия:** 2.0
> **Дата:** 2026
> **См. также:** [`1-task-workflow-doc.md`](./1-task-workflow-doc.md), [`mqtt-rpc-protocol.md`](./mqtt-rpc-protocol.md), [`mqtt-rpc-client-flow.md`](./mqtt-rpc-client-flow.md), [`task_states.md`](./task_states.md), [`TTL.md`](./TTL.md)

Диаграммы ниже отражают полный жизненный цикл задачи устройства: от REST-инициации клиентом до доставки результата (через polling или webhook). Используются реальные имена топиков и этапов RPC по MQTT v5: `tsk`, `ack`, `req`, `rsp`, `res`, `cmt`, а также статусы задач из [`task_states.md`](./task_states.md).

> **Замечание о цвете.** Эти диаграммы намеренно не используют `box`/`rect rgb(...)` с произвольной заливкой: на GitHub текст внутри Mermaid использует цвет темы (тёмный в светлой / светлый в тёмной), и плотные RGB-фоны делают подписи нечитаемыми хотя бы в одной из тем. Поэтому для группировки используются нейтральные конструкции `alt`/`opt`/`par`/`loop` и `Note`, которые корректно отрисовываются в обеих темах GitHub.

---

## 1. Создание задачи через REST API (touch_task)

Клиентское приложение создаёт задачу по `POST /api/v1/device-tasks/`. API валидирует запрос, Core сохраняет задачу в статусе `READY`, затем параллельно ставит её в очередь устройства и (опционально) триггерит устройство по MQTT.

```mermaid
sequenceDiagram
    autonumber
    actor ClientApp as Client App
    participant API as REST API
    participant Core as Cloud Core
    participant Queue as Task Queue
    participant Broker as MQTT Broker
    participant Device

    ClientApp->>+API: POST /device-tasks (device_id, method_code, priority, ttl, payload)
    Note over API: Auth (api-key/JWT/cert), validate headers and body

    alt Valid request
        API->>+Core: Create task
        Core-->>-API: task_id (UUID4), status = READY
        API-->>-ClientApp: 200 OK { id, created_at }

        par Persist for polling
            Core->>Queue: Enqueue task (priority, ttl, created_at)
        and Optional trigger (push)
            alt Device is online
                Core->>Broker: PUBLISH srv/<SN>/tsk [correlationData = task_id, method_code]
                Broker->>Device: DELIVER tsk
                opt Optional ACK
                    Device->>Broker: PUBLISH dev/<SN>/ack
                    Broker->>Core: DELIVER ack
                    Core->>Core: status = PENDING
                end
            else Device is offline
                Note over Core,Broker: Push не доставлен — задача остаётся в очереди и будет выдана при следующем polling запросе устройства
            end
        end
    else Invalid request
        API-->>ClientApp: 4xx Error (validation / auth)
    end
```

---

## 2. Выполнение задачи устройством (RPC по MQTT v5)

Устройство забирает задачу одним из двух способов: **Trigger** (после `tsk` от сервера) или **Polling** (периодический `req` с нулевым UUID). Дальнейший конвейер `req → rsp → res → cmt` идентичен.

Стратегия выбора задачи при polling-запросе с `correlationData = UUID(0)` (см. [`1-task-workflow-doc.md`](./1-task-workflow-doc.md)):

1. участвуют только задачи устройства со `status < DONE`
2. задачи с `ttl = 0` исключаются из выборки
3. сортировка: `priority DESC` → `ttl ASC` (положительный) → `created_at ASC`

```mermaid
sequenceDiagram
    autonumber
    participant Core as Cloud Core
    participant Queue as Task Queue
    participant Broker as MQTT Broker
    participant Device

    alt Trigger (server-initiated)
        Note over Core,Device: correlationData = task_id (назначен сервером)
        Core->>Broker: PUBLISH srv/<SN>/tsk [method_code]
        Broker->>Device: DELIVER tsk
        Device->>Broker: PUBLISH dev/<SN>/req [correlationData = task_id]
    else Polling (device-initiated)
        Note over Device: Периодический тик req_poll_timer — пустые ответы тихо игнорируются
        Device->>Broker: PUBLISH dev/<SN>/req [correlationData = UUID(0)]
    end

    Broker->>Core: DELIVER req
    Core->>Queue: Select next task (priority/ttl/created_at)
    alt No eligible task
        Note over Core: Тихо игнорируется — устройство ждёт следующего тика
    else Task selected
        Core->>Core: status = LOCK (locked_at)
        Core->>Broker: PUBLISH srv/<SN>/rsp [method_code, payload.dt]
        Broker->>Device: DELIVER rsp

        Note over Device: Worker выполняет задачу

        Device->>Broker: PUBLISH dev/<SN>/res [status_code = 200/4xx/500, ext_id]
        Broker->>Core: DELIVER res
        Core->>Core: Save result, status = DONE / FAILED
        Core->>Broker: PUBLISH srv/<SN>/cmt [result_id]
        Broker->>Device: DELIVER cmt
        Note over Core,Device: RPC lifecycle complete
    end
```

> Истечение TTL обрабатывается отдельно: задача с истёкшим сроком переводится в `EXPIRED` и больше не выдаётся устройству. Подробнее — [`TTL.md`](./TTL.md), [`task_states.md`](./task_states.md).

---

## 3. Получение результата клиентом: polling vs webhook

Клиент может либо периодически опрашивать статус задачи через REST, либо подписаться на webhook `msg-task-result` и получать результат push-нотификацией (рекомендуется для нагруженных систем).

```mermaid
sequenceDiagram
    autonumber
    actor ClientApp as Client App
    participant API as REST API
    participant Core as Cloud Core
    participant Hook as Client Webhook Endpoint

    alt Polling (pull)
        loop Until status in {DONE, FAILED, EXPIRED, DELETED}
            ClientApp->>+API: GET /device-tasks/{id}
            Note over API: Auth + headers validation
            API->>Core: Read task data
            Core-->>API: task { status, results[] }
            API-->>-ClientApp: 200 OK (status, results)
        end
    else Webhook (push)
        Note over ClientApp,Hook: Webhook предварительно зарегистрирован<br/>через PUT /api/v1/webhooks/msg-task-result
        Core->>+Hook: POST /hooks/task-result/{task_id}<br/>X-Msg-Type, X-Device-Id, X-Ext-Id, X-Result-Id, X-Status-Code
        Hook-->>-Core: 2xx ack
        Note over Hook,ClientApp: Несколько результатов одной задачи<br/>доставляются отдельными хуками
    end
```

---

## 4. Сводный сценарий end-to-end

Связка всех трёх диаграмм в одном потоке для удобства: `touch_task` → доставка устройству → выполнение → доставка результата клиенту.

```mermaid
sequenceDiagram
    autonumber
    actor ClientApp as Client App
    participant API as REST API
    participant Core as Cloud Core
    participant Broker as MQTT Broker
    participant Device

    ClientApp->>API: POST /device-tasks (touch_task)
    API->>Core: Create task (status = READY)
    API-->>ClientApp: 200 OK { task_id }

    opt Trigger
        Core->>Broker: srv/<SN>/tsk
        Broker->>Device: tsk
        opt ACK
            Device->>Core: dev/<SN>/ack  (status = PENDING)
        end
    end

    Device->>Core: dev/<SN>/req  (status = LOCK)
    Core->>Device: srv/<SN>/rsp [payload]
    Note over Device: Execute
    Device->>Core: dev/<SN>/res [status_code]
    Core->>Core: Save result (status = DONE / FAILED)
    Core->>Device: srv/<SN>/cmt [result_id]

    alt Webhook subscribed
        Core-->>ClientApp: POST webhook msg-task-result
    else Polling
        loop
            ClientApp->>API: GET /device-tasks/{id}
            API-->>ClientApp: task { status, results[] }
        end
    end
```
