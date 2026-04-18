# LEO4 MCP Server – Architecture

## System Overview

```mermaid
flowchart TB
    subgraph Clients["AI Clients"]
        CL["Claude Desktop"]
        VS["VS Code / Copilot"]
        CU["Cursor"]
    end

    subgraph MCP["leo4-mcp (this server)"]
        direction TB
        SRV["server.py\nFastMCP instance"]
        TOOLS["Tools Layer\ntasks / events / webhooks / composite"]
        CLIENT["Leo4Client\nhttpx AsyncClient + retries"]
        CFG["Settings\npydantic-settings"]
        DRY["DryRun\nmock responses"]
    end

    subgraph LEO4["LEO4 Platform"]
        REST["REST API\nhttps://dev.leo4.ru/api/v1"]
        BROKER["RabbitMQ / MQTT Broker"]
    end

    subgraph Devices["IoT Devices"]
        ESP["ESP32 Firmware"]
        STM["STM32 Firmware"]
    end

    subgraph Hooks["Webhook Receiver (optional)"]
        INBOX["webhook_inbox.py\nFastAPI + in-memory queue"]
    end

    Clients <-->|"MCP stdio/SSE"| SRV
    SRV --> TOOLS
    TOOLS --> CLIENT
    TOOLS -.->|"dry_run=True"| DRY
    CLIENT <-->|"HTTPS\nx-api-key header"| REST
    REST <-->|"AMQP"| BROKER
    BROKER <-->|"TCP/TLS"| ESP
    BROKER <-->|"TCP/TLS"| STM
    REST -->|"HTTP POST\nwebhook"| INBOX
```

---

## Open-Cell Full Cycle

The `open_cell_and_confirm` composite tool performs three steps to guarantee physical confirmation:

```mermaid
sequenceDiagram
    participant AI as AI Assistant
    participant MCP as leo4-mcp
    participant API as LEO4 REST API
    participant RMQ as RabbitMQ
    participant DEV as IoT Device (ESP32)

    AI->>MCP: open_cell_and_confirm(device_id=4619, cell_number=5)

    note over MCP,API: Step 1 – Send command
    MCP->>API: POST /device-tasks/\n{method_code:51, payload:{dt:[{cl:5}]}}
    API-->>MCP: {id:"task-uuid", created_at:...}

    note over MCP,API: Step 2 – Confirm delivery
    MCP->>API: GET /device-tasks/task-uuid
    API-->>MCP: {status:0, status_name:"READY"}
    note over API,DEV: API pushes task via RabbitMQ
    API->>RMQ: publish task
    RMQ->>DEV: deliver task
    DEV-->>RMQ: ACK
    RMQ-->>API: delivered
    MCP->>API: GET /device-tasks/task-uuid
    API-->>MCP: {status:3, status_name:"DONE"}
    note over MCP: DONE = delivered only, NOT physically executed

    note over MCP,DEV: Step 3 – Physical confirmation via event polling
    DEV->>DEV: physically opens cell 5
    DEV->>RMQ: publish CellOpenEvent\n{event_type_code:13, tag:304, value:5}
    RMQ->>API: store event
    MCP->>API: GET /device-events/fields/\n?event_type_code=13&tag=304
    API-->>MCP: [{value:5, created_at:...}]

    MCP-->>AI: {task:{...}, delivery:{status:3},\nphysical_confirmation:{confirmed:true, event:{value:5}}}
```

---

## Task Lifecycle State Machine

```mermaid
stateDiagram-v2
    [*] --> READY : POST /device-tasks/
    READY --> PENDING : Device contacts broker
    PENDING --> LOCK : Device starts executing
    LOCK --> DONE : Command delivered to device
    READY --> EXPIRED : TTL elapsed
    PENDING --> EXPIRED : TTL elapsed
    LOCK --> FAILED : Execution error
    DONE --> DELETED : DELETE /device-tasks/{id}
    EXPIRED --> [*]
    FAILED --> [*]
    DELETED --> [*]

    note right of DONE
        status=3 means DELIVERY only
        Physical execution confirmed
        via CellOpenEvent (code=13)
    end note
```

---

## Composite Tools

Composite tools in `leo4_mcp/tools/composite.py` combine multiple API calls into single high-level operations:

| Composite Tool | Steps | Use Case |
|----------------|-------|----------|
| `hello` | create_task → get_status | Ping / connectivity check |
| `open_cell_and_confirm` | create_task → get_status → poll_event | Full locker open cycle |
| `reboot_device` | create_task → get_status | Remote reboot |
| `bind_card_to_cell` | create_task → get_status | Access control setup |
| `write_nvs` | create_task → get_status | Remote config write |
| `read_nvs` | create_task → get_status | Remote config read |
| `mass_activate` | asyncio.gather N × create_task | Broadcast to many devices |

---

## Webhook Mode vs Polling

```mermaid
flowchart LR
    subgraph Polling["Polling Mode (default)"]
        P1["poll_device_event()\nsleep 2s loop"]
        P2["GET /device-events/fields/\nevery 2 seconds"]
        P1 --> P2
        P2 --> P1
    end

    subgraph Webhook["Webhook Mode (production)"]
        W1["configure_webhook()\nPUT /webhooks/msg-event"]
        W2["LEO4 Platform\nsends HTTP POST"]
        W3["webhook_inbox.py\nFastAPI receiver"]
        W4["GET /inbox/events"]
        W1 --> W2
        W2 --> W3
        W3 --> W4
    end

    note1["Polling: simple, works anywhere\nWebhooks: real-time, production-grade"]
```

**Recommendation**: Use `poll_device_event` for development and low-volume scenarios. Use `configure_webhook` + `webhook_inbox.py` for production deployments where latency matters.

---

## Module Structure

```
mcp/
├── leo4_mcp/
│   ├── __init__.py          # Package version
│   ├── __main__.py          # CLI entry point (argparse)
│   ├── config.py            # pydantic-settings (LEO4_* env vars)
│   ├── client.py            # Leo4Client – async httpx with retries
│   ├── dry_run.py           # Deterministic mock responses
│   ├── resources.py         # MCP resource handlers
│   ├── prompts.py           # MCP prompt templates
│   ├── server.py            # FastMCP server, tool/resource registration
│   ├── webhook_inbox.py     # Optional FastAPI webhook receiver
│   └── tools/
│       ├── tasks.py         # create_device_task, get_task_status, list_device_tasks
│       ├── events.py        # get_recent_events, get_telemetry, poll_device_event
│       ├── webhooks.py      # configure_webhook, list_webhooks
│       └── composite.py     # hello, open_cell_and_confirm, reboot_device, ...
├── tests/
│   ├── test_client.py
│   ├── test_tools_tasks.py
│   ├── test_tools_events.py
│   └── test_composite.py
├── examples/
│   ├── claude_desktop_config.json
│   ├── vscode_mcp.json
│   ├── cursor_mcp.json
│   └── curl_smoke_test.sh
├── docs/
│   ├── architecture.md      # This file
│   ├── tools-reference.md
│   └── deep-dive.md
├── pyproject.toml
├── .env.example
└── README.md
```
