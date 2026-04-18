# LEO4 MCP Tools Reference

Complete reference for all 15 MCP tools exposed by the LEO4 MCP server.

---

## Table of Contents

- [Task Tools](#task-tools)
  - [create_device_task](#create_device_task)
  - [get_task_status](#get_task_status)
  - [list_device_tasks](#list_device_tasks)
- [Event Tools](#event-tools)
  - [get_recent_events](#get_recent_events)
  - [get_telemetry](#get_telemetry)
  - [poll_device_event](#poll_device_event)
- [Webhook Tools](#webhook-tools)
  - [configure_webhook](#configure_webhook)
  - [list_webhooks](#list_webhooks)
- [Composite Tools](#composite-tools)
  - [hello](#hello)
  - [open_cell_and_confirm](#open_cell_and_confirm)
  - [reboot_device](#reboot_device)
  - [bind_card_to_cell](#bind_card_to_cell)
  - [write_nvs](#write_nvs)
  - [read_nvs](#read_nvs)
  - [mass_activate](#mass_activate)

---

## Task Tools

### create_device_task

**Description**: Create a task for an IoT device. Sends a command to the LEO4 platform which delivers it to the device via the message broker.

> ⚠️ This creates the task only. `status=3 (DONE)` from `get_task_status` means **delivery**, not physical execution.

**Endpoint**: `POST /device-tasks/`

**Parameters**:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `device_id` | int | ✅ | — | LEO4 device identifier |
| `method_code` | int | ✅ | — | Command code (20=hello, 21=reboot, 51=open cell, 16=bind, 49=write NVS, 50=read NVS) |
| `payload` | dict | ❌ | `null` | Command parameters object (see method code table) |
| `ttl` | int | ❌ | `5` | Task time-to-live in minutes |
| `priority` | int | ❌ | `1` | Priority 0–9 (higher = more urgent) |
| `ext_task_id` | string | ❌ | auto UUID | Idempotency key (your reference ID) |

**Output**:

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "created_at": 1712345678
}
```

**Example call**:

```json
{
  "tool": "create_device_task",
  "arguments": {
    "device_id": 4619,
    "method_code": 51,
    "payload": {"dt": [{"cl": 5}]},
    "ttl": 5,
    "priority": 1,
    "ext_task_id": "order-12345-open-cell-5"
  }
}
```

**Common errors**:
- `401` – invalid `LEO4_API_KEY`
- `422` – invalid payload structure
- `ValueError` – device_id not in `LEO4_ALLOWED_DEVICE_IDS`

---

### get_task_status

**Description**: Retrieve the current status of a task. Poll until `status=3` (DONE) to confirm delivery.

**Endpoint**: `GET /device-tasks/{id}`

**Parameters**:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `task_id` | string | ✅ | — | UUID returned by `create_device_task` |

**Output**:

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": 3,
  "status_name": "DONE",
  "device_id": 4619,
  "method_code": 51,
  "ttl": 5,
  "priority": 1,
  "ext_task_id": "order-12345-open-cell-5",
  "created_at": 1712345678,
  "results": []
}
```

**Status codes**:

| Code | Name | Meaning |
|------|------|---------|
| 0 | READY | Queued, device not yet contacted |
| 1 | PENDING | Device acknowledged |
| 2 | LOCK | Device processing |
| **3** | **DONE** | **Delivered (NOT physically executed!)** |
| 4 | EXPIRED | TTL elapsed |
| 5 | DELETED | Manually deleted |
| 6 | FAILED | Delivery failed |

**Example call**:

```json
{
  "tool": "get_task_status",
  "arguments": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000"
  }
}
```

---

### list_device_tasks

**Description**: List recent tasks for a device.

**Endpoint**: `GET /device-tasks/?device_id=N`

**Parameters**:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `device_id` | int | ✅ | — | LEO4 device identifier |
| `limit` | int | ❌ | `50` | Maximum results per page |

**Output**:

```json
{
  "items": [...],
  "total": 42,
  "page": 1,
  "size": 50,
  "pages": 1
}
```

---

## Event Tools

### get_recent_events

**Description**: Fetch recent events for a device from `GET /device-events/fields/`. Returns time-series field values.

**Endpoint**: `GET /device-events/fields/`

**Parameters**:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `device_id` | int | ✅ | — | LEO4 device identifier |
| `event_type_code` | int | ❌ | `null` | Filter by event type (e.g. 13=CellOpenEvent) |
| `tag` | int | ❌ | `null` | Filter by tag (e.g. 304=cell number) |
| `interval_m` | int | ❌ | `5` | Look-back window in minutes |
| `limit` | int | ❌ | `50` | Maximum events |

**Output**:

```json
[
  {
    "value": 5,
    "created_at": "2026-01-01T12:00:00Z",
    "interval_sec": 10
  }
]
```

**Example call**:

```json
{
  "tool": "get_recent_events",
  "arguments": {
    "device_id": 4619,
    "event_type_code": 13,
    "tag": 304,
    "interval_m": 10
  }
}
```

---

### get_telemetry

**Description**: Retrieve telemetry/health data for a device. Similar to `get_recent_events` but defaults to a longer 60-minute window.

**Endpoint**: `GET /device-events/fields/`

**Parameters**:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `device_id` | int | ✅ | — | LEO4 device identifier |
| `event_type_code` | int | ❌ | `null` | Filter by event type |
| `interval_m` | int | ❌ | `60` | Look-back window in minutes |
| `limit` | int | ❌ | `100` | Maximum events |

---

### poll_device_event

**Description**: Poll `GET /device-events/fields/` every 2 seconds until a matching event is found or timeout is reached. Use after `get_task_status` returns `DONE` to confirm physical execution.

**Endpoint**: `GET /device-events/fields/` (polled)

**Parameters**:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `device_id` | int | ✅ | — | LEO4 device identifier |
| `event_type_code` | int | ✅ | — | Event type to watch (e.g. 13=CellOpenEvent) |
| `tag` | int | ✅ | — | Tag to filter (e.g. 304=cell number) |
| `expected_value` | int | ❌ | `null` | If set, only match events where value equals this |
| `interval_m` | int | ❌ | `5` | Look-back window per poll |
| `timeout_s` | int | ❌ | `30` | Total wait time in seconds |

**Output (success)**:

```json
{
  "confirmed": true,
  "event": {
    "value": 5,
    "created_at": "2026-01-01T12:00:05Z",
    "interval_sec": 8
  }
}
```

**Output (timeout)**:

```json
{
  "confirmed": false,
  "event_type_code": 13,
  "tag": 304,
  "expected_value": 5,
  "message": "No matching event found within 30s"
}
```

**Example call**:

```json
{
  "tool": "poll_device_event",
  "arguments": {
    "device_id": 4619,
    "event_type_code": 13,
    "tag": 304,
    "expected_value": 5,
    "timeout_s": 30
  }
}
```

---

## Webhook Tools

### configure_webhook

**Description**: Create or update a webhook endpoint that LEO4 will POST to when events occur.

**Endpoint**: `PUT /webhooks/{event_type}`

**Parameters**:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `event_type` | string | ✅ | — | `"msg-event"` or `"msg-task-result"` |
| `url` | string | ✅ | — | HTTPS URL to receive webhook POSTs |
| `headers` | dict | ❌ | `null` | Additional headers included in webhook requests |
| `is_active` | bool | ❌ | `true` | Whether the webhook is active |

**Output**:

```json
{
  "id": 1,
  "event_type": "msg-event",
  "url": "https://my-app.com/hooks/events",
  "headers": {"Authorization": "Bearer secret"},
  "is_active": true
}
```

**Example call**:

```json
{
  "tool": "configure_webhook",
  "arguments": {
    "event_type": "msg-event",
    "url": "https://my-app.com/hooks/iot-events",
    "headers": {"X-Secret": "my-shared-secret"},
    "is_active": true
  }
}
```

---

### list_webhooks

**Description**: List all configured webhooks for the current organisation.

**Endpoint**: `GET /webhooks/`

**Parameters**: none

**Output**:

```json
[
  {
    "id": 1,
    "event_type": "msg-event",
    "url": "https://my-app.com/hooks/events",
    "is_active": true
  }
]
```

---

## Composite Tools

### hello

**Description**: Send a hello/ping command (`method_code=20, mt=0`) to a device and return the delivery status.

**Parameters**:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `device_id` | int | ✅ | — | LEO4 device identifier |

**Output**: Task status object (see `get_task_status`)

**Example**: `{"tool": "hello", "arguments": {"device_id": 4619}}`

---

### open_cell_and_confirm

**Description**: Full 3-step cycle to open a locker cell and confirm physical execution:
1. `POST /device-tasks/` with `method_code=51`
2. `GET /device-tasks/{id}` until `status=3`
3. Poll `GET /device-events/fields/` for `CellOpenEvent (code=13, tag=304, value=cell_number)`

**Parameters**:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `device_id` | int | ✅ | — | LEO4 device identifier |
| `cell_number` | int | ✅ | — | Cell number to open |
| `ttl` | int | ❌ | `5` | Task TTL in minutes |
| `timeout_s` | int | ❌ | `30` | Seconds to wait for physical confirmation |

**Output**:

```json
{
  "task": {"id": "...", "created_at": 1712345678},
  "delivery": {"id": "...", "status": 3, "status_name": "DONE"},
  "physical_confirmation": {
    "confirmed": true,
    "event": {"value": 5, "created_at": "2026-01-01T12:00:05Z"}
  }
}
```

**Example call**:

```json
{
  "tool": "open_cell_and_confirm",
  "arguments": {
    "device_id": 4619,
    "cell_number": 5,
    "timeout_s": 30
  }
}
```

---

### reboot_device

**Description**: Reboot a device (`method_code=21`). Returns delivery status. Physical reboot is confirmed by reconnect event.

**Parameters**:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `device_id` | int | ✅ | — | LEO4 device identifier |
| `ttl` | int | ❌ | `5` | Task TTL in minutes |

---

### bind_card_to_cell

**Description**: Bind a card or PIN code to a specific cell (`method_code=16`).

**Parameters**:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `device_id` | int | ✅ | — | LEO4 device identifier |
| `cell_number` | int | ✅ | — | Target cell |
| `card_code` | string | ✅ | — | Card or PIN code to bind |
| `ttl` | int | ❌ | `5` | Task TTL in minutes |

---

### write_nvs

**Description**: Write a value to non-volatile storage on a device (`method_code=49`). Used for remote configuration.

**Parameters**:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `device_id` | int | ✅ | — | LEO4 device identifier |
| `namespace` | string | ✅ | — | NVS namespace |
| `key` | string | ✅ | — | NVS key |
| `value` | string | ✅ | — | Value to write |
| `type` | string | ✅ | — | Value type: `"str"`, `"i32"`, `"blob"` |
| `ttl` | int | ❌ | `5` | Task TTL in minutes |

**Example call**:

```json
{
  "tool": "write_nvs",
  "arguments": {
    "device_id": 4619,
    "namespace": "wifi",
    "key": "ssid",
    "value": "MyNetwork",
    "type": "str"
  }
}
```

---

### read_nvs

**Description**: Read a value from NVS on a device (`method_code=50`). The value is returned in the task results.

**Parameters**:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `device_id` | int | ✅ | — | LEO4 device identifier |
| `namespace` | string | ✅ | — | NVS namespace |
| `key` | string | ✅ | — | NVS key to read |
| `ttl` | int | ❌ | `5` | Task TTL in minutes |

---

### mass_activate

**Description**: Send the same command to multiple devices concurrently using `asyncio.gather`. All tasks are created in parallel.

**Parameters**:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `device_ids` | list[int] | ✅ | — | List of device identifiers |
| `method_code` | int | ✅ | — | Command code |
| `payload` | dict | ✅ | — | Command parameters |
| `ttl` | int | ❌ | `5` | Task TTL in minutes |

**Output**:

```json
{
  "total": 3,
  "success": 2,
  "failed": 1,
  "results": [
    {"device_id": 4619, "task": {"id": "...", "created_at": 1712345678}},
    {"device_id": 4620, "task": {"id": "...", "created_at": 1712345678}},
    {"device_id": 4621, "error": "LEO4 API error 422: ..."}
  ]
}
```

**Example call**:

```json
{
  "tool": "mass_activate",
  "arguments": {
    "device_ids": [4619, 4620, 4621],
    "method_code": 20,
    "payload": {"dt": [{"mt": 0}]},
    "ttl": 5
  }
}
```
