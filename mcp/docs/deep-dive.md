# LEO4 REST API – Deep Dive

Reference for all LEO4 REST API endpoints, data types, method codes, and event types used by this MCP server.

---

## Base URL & Authentication

| Item | Value |
|------|-------|
| Base URL | `https://dev.leo4.ru/api/v1` |
| Auth header | `x-api-key: ApiKey <YOUR_KEY>` |
| Content-Type | `application/json` |

---

## All Endpoints

### Device Tasks

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/device-tasks/` | Create a new task |
| `GET` | `/device-tasks/{id}` | Get task by ID |
| `GET` | `/device-tasks/?device_id=N` | List tasks for device (paginated) |
| `DELETE` | `/device-tasks/{id}` | Delete a task |

#### POST /device-tasks/ – Request Body

```json
{
  "device_id": 4619,
  "method_code": 51,
  "ttl": 5,
  "priority": 1,
  "ext_task_id": "your-idempotency-key",
  "payload": {"dt": [{"cl": 5}]}
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `device_id` | int | ✅ | Target device |
| `method_code` | int | ✅ | Command type (see table below) |
| `ttl` | int | ✅ | Time-to-live in minutes |
| `priority` | int | ✅ | 0–9, higher is more urgent |
| `ext_task_id` | string | ✅ | Your idempotency/reference key |
| `payload` | object | ❌ | Command-specific parameters |

#### GET /device-tasks/ – Query Parameters

| Param | Type | Description |
|-------|------|-------------|
| `device_id` | int | Filter by device |
| `size` | int | Page size |
| `page` | int | Page number |

#### Task Object Response

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": 3,
  "status_name": "DONE",
  "device_id": 4619,
  "method_code": 51,
  "ttl": 5,
  "priority": 1,
  "ext_task_id": "your-ref",
  "created_at": 1712345678,
  "payload": {"dt": [{"cl": 5}]},
  "results": []
}
```

---

### Device Events

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/device-events/fields/` | Time-series field values (main polling endpoint) |
| `GET` | `/device-events/` | Full event objects (paginated) |
| `GET` | `/device-events/incremental` | Incremental events by last_event_id |

#### GET /device-events/fields/ – Query Parameters

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `device_id` | int | ✅ | Target device |
| `event_type_code` | int | ❌ | Filter by event type |
| `tag` | int | ❌ | Filter by tag |
| `interval_m` | int | ❌ | Look-back window in minutes |
| `limit` | int | ❌ | Max results |

#### Field Value Response

```json
[
  {
    "value": 5,
    "created_at": "2026-01-01T12:00:00Z",
    "interval_sec": 10
  }
]
```

#### GET /device-events/incremental – Query Parameters

| Param | Type | Description |
|-------|------|-------------|
| `device_id` | int | Target device |
| `last_event_id` | int | Return events after this ID |
| `limit` | int | Max results |

---

### Devices

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/devices/` | List devices |
| `PUT` | `/devices/{device_id}` | Update device (add tags) |

#### GET /devices/ – Query Parameters

| Param | Type | Description |
|-------|------|-------------|
| `device_id` | int | Filter by specific device |

---

### Webhooks

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/webhooks/` | List all webhooks |
| `PUT` | `/webhooks/{event_type}` | Create or update webhook |
| `DELETE` | `/webhooks/{event_type}` | Delete webhook |

Supported `event_type` values:
- `msg-event` – device events (cell open, sensor readings, etc.)
- `msg-task-result` – task delivery notifications

#### PUT /webhooks/{event_type} – Request Body

```json
{
  "url": "https://my-app.com/hooks/iot",
  "is_active": true,
  "headers": {
    "X-Shared-Secret": "abc123"
  }
}
```

---

## Method Codes

| Code | Name | Payload Format | Description |
|------|------|---------------|-------------|
| `20` | Short command / Hello | `{"dt": [{"mt": 0}]}` | Ping device. Use `mt=0` for hello, `mt=4` to list cells |
| `21` | Reboot | `{"dt": [{"mt": 0}]}` | Reboot the device |
| `51` | Open cell | `{"dt": [{"cl": N}]}` | Open cell number N |
| `16` | Bind card / PIN | `{"dt": [{"cl": N, "cd": "CODE"}]}` | Bind card/PIN to cell |
| `49` | Write NVS | `{"dt": [{"ns": "ns", "k": "key", "v": "val", "t": "str"}]}` | Write to non-volatile storage |
| `50` | Read NVS | `{"dt": [{"ns": "ns", "k": "key"}]}` | Read from non-volatile storage |

### Payload Field Reference

| Field | Used In | Description |
|-------|---------|-------------|
| `mt` | code 20, 21 | Message type (0=hello, 4=list cells) |
| `cl` | code 51, 16 | Cell number |
| `cd` | code 16 | Card or PIN code string |
| `ns` | code 49, 50 | NVS namespace |
| `k` | code 49, 50 | NVS key |
| `v` | code 49 | NVS value |
| `t` | code 49 | NVS type (`"str"`, `"i32"`, `"blob"`) |

---

## Event Types

| Code | Name | Description | Key Tags |
|------|------|-------------|---------|
| `1` | DeviceConnectEvent | Device connected to broker | — |
| `2` | DeviceDisconnectEvent | Device disconnected | — |
| `3` | HealthCheckEvent | Periodic heartbeat | tag 301=battery, 302=signal, 303=temp |
| `13` | CellOpenEvent | Cell physically opened | **tag 304=cell number** |

### Key Tags Reference

| Tag | Used In | Description |
|-----|---------|-------------|
| `301` | HealthCheckEvent | Battery level (%) |
| `302` | HealthCheckEvent | Signal strength (dBm or %) |
| `303` | HealthCheckEvent | Temperature (°C) |
| `304` | CellOpenEvent | Cell number that was opened |

### CellOpenEvent Example

```json
{
  "id": 12345,
  "device_id": 4619,
  "event_type_code": 13,
  "created_at": "2026-01-01T12:00:05Z",
  "data": {"304": 5}
}
```

When using `GET /device-events/fields/` with `tag=304`:

```json
[{"value": 5, "created_at": "2026-01-01T12:00:05Z", "interval_sec": 8}]
```

---

## Task Status Reference

| Code | Name | Meaning | Terminal? |
|------|------|---------|-----------|
| `0` | READY | Queued, device not yet contacted | No |
| `1` | PENDING | Device acknowledged receipt | No |
| `2` | LOCK | Device is processing | No |
| `3` | **DONE** | **Command delivered (NOT physically executed)** | Yes |
| `4` | EXPIRED | TTL elapsed before delivery | Yes |
| `5` | DELETED | Manually deleted | Yes |
| `6` | FAILED | Delivery failed | Yes |

---

## Pagination

Endpoints that return lists use a consistent pagination envelope:

```json
{
  "items": [...],
  "total": 100,
  "page": 1,
  "size": 50,
  "pages": 2
}
```

Use `?page=2&size=50` query parameters to paginate.

---

## Error Responses

| HTTP Status | Meaning | MCP Handling |
|-------------|---------|--------------|
| `200` | Success | Return JSON body |
| `401` | Unauthorized | Raise `Leo4ApiError(401, ...)` immediately |
| `403` | Forbidden | Raise `Leo4ApiError(403, ...)` immediately |
| `404` | Not Found | Raise `Leo4ApiError(404, ...)` immediately |
| `422` | Validation Error | Raise `Leo4ApiError(422, ...)` immediately |
| `5xx` | Server Error | Retry up to `LEO4_HTTP_RETRIES` times with backoff |

---

## What Is NOT Covered (TODO / Roadmap)

The following LEO4 API capabilities exist but are not yet exposed as MCP tools:

| Feature | Endpoint | Status |
|---------|----------|--------|
| Incremental event polling | `GET /device-events/incremental` | TODO |
| Add device tag | `PUT /devices/{device_id}` | TODO |
| Delete webhook | `DELETE /webhooks/{event_type}` | TODO |
| List full events | `GET /device-events/` (paginated) | TODO |
| Task deletion | `DELETE /device-tasks/{id}` | TODO |
| List cells (mt=4) | method_code=20, mt=4 | TODO (via create_device_task) |

### Incremental Events Pattern

For high-frequency production use, the incremental endpoint is more efficient than `fields/`:

```bash
GET /device-events/incremental?device_id=4619&last_event_id=0&limit=100
# Returns events newer than last_event_id
# Store max(id) and use as last_event_id in next call
```

This avoids re-scanning the same time window on every poll.
