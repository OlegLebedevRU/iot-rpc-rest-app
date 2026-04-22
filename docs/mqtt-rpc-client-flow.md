# MQTT RPC Client Flow — Mermaid Diagrams

> **File:** `docs/mqtt-rpc-client-flow.md`
> **Version:** 1.1
> **Date:** 2026
> **See also:** [`mqtt-rpc-protocol.md`](mqtt-rpc-protocol.md), [`correlation-data-guide.md`](correlation-data-guide.md), [`event-property-tags.md`](event-property-tags.md)

> ⚠️ **Статус документа:** этот файл является **графической репликой** основного протокола [`mqtt-rpc-protocol.md`](./mqtt-rpc-protocol.md). Все диаграммы должны актуализироваться при изменении протокола. Текстовые описания правил и алгоритмов намеренно вынесены в профильные документы — в данном файле приведены только ссылки.

---

## 1. Device-Side Client Logic (Flowchart)

High-level decision flow executed by the MQTT client on the device for every incoming message.

```mermaid
flowchart TD
    START([Device connected to MQTT broker over TLS]) --> SUB

    SUB["Subscribe: srv/&lt;SN&gt;/tsk, rsp, cmt, eva"]

    SUB --> TIMERS["Start req_poll_timer and healthcheck_timer"]

    TIMERS --> WAIT{{"Wait for event"}}

    %% --- Polling path ---
    WAIT -->|req_poll_timer fires| POLL_REQ["Publish dev/&lt;SN&gt;/req with zero UUID"]
    POLL_REQ --> WAIT_RSP{{"Wait for srv/&lt;SN&gt;/rsp"}}
    WAIT_RSP -->|No task / timeout| WAIT
    WAIT_RSP -->|rsp received| GOT_RSP

    %% --- Trigger path ---
    WAIT -->|tsk on srv/&lt;SN&gt;/tsk| GOT_TSK["Extract correlationData and method_code"]
    GOT_TSK --> OPT_ACK["Optional: Publish dev/&lt;SN&gt;/ack"]
    OPT_ACK --> TRIG_REQ["Publish dev/&lt;SN&gt;/req with UUID from tsk"]
    TRIG_REQ --> GOT_RSP

    %% --- Common RSP processing ---
    GOT_RSP["rsp on srv/&lt;SN&gt;/rsp: extract method_code and payload.dt"] --> IS_INTERACTIVE

    IS_INTERACTIVE{{"Interactive\nmethod_code?\n3000-3999 or 0xFFFF"}}

    IS_INTERACTIVE -->|Yes| CHECK_WS{{"Active WS client?"}}
    CHECK_WS -->|No WS or start failed| FAIL_FAST["Publish dev/&lt;SN&gt;/res status=500"]
    FAIL_FAST --> WAIT_CMT

    CHECK_WS -->|WS active| EXEC_TASK
    IS_INTERACTIVE -->|No| EXEC_TASK["Execute task with payload.dt"]

    EXEC_TASK --> PUB_RES["Publish dev/&lt;SN&gt;/res status=200/4xx/500"]
    PUB_RES --> WAIT_CMT

    WAIT_CMT{{"Wait for srv/&lt;SN&gt;/cmt"}}
    WAIT_CMT -->|cmt received| DONE_RPC["RPC complete: extract result_id"]
    DONE_RPC --> WAIT

    %% --- Async event path ---
    WAIT -->|healthcheck_timer or internal event| PUB_EVT["Publish dev/&lt;SN&gt;/evt with new UUID"]
    PUB_EVT --> OPT_EVA{{"Wait for srv/&lt;SN&gt;/eva"}}
    OPT_EVA -->|eva received or timeout| WAIT
```

---

## 2. Trigger Flow — Server-Initiated RPC (Sequence)

The server announces a task directly; the device picks it up and executes it.

```mermaid
sequenceDiagram
    autonumber
    participant S  as Server (Cloud Core)
    participant B  as MQTT Broker
    participant D  as Device (Client)

    Note over S,D: corr = a1b2c3d4-... assigned by server

    S  ->> B : PUBLISH srv/<SN>/tsk [method=51]
    B  ->> D : DELIVER tsk

    opt Optional ACK
        D ->> B : PUBLISH dev/<SN>/ack
        B ->> S : DELIVER ack
    end

    D  ->> B : PUBLISH dev/<SN>/req
    B  ->> S : DELIVER req

    S  ->> B : PUBLISH srv/<SN>/rsp [method=51]
    B  ->> D : DELIVER rsp

    Note over D: Execute task with payload.dt

    D  ->> B : PUBLISH dev/<SN>/res [status=200]
    B  ->> S : DELIVER res

    S  ->> B : PUBLISH srv/<SN>/cmt [result_id=67890]
    B  ->> D : DELIVER cmt

    Note over S,D: RPC lifecycle complete
```

---

## 3. Polling Flow — Device-Initiated RPC (Sequence)

The device polls for pending tasks using a zero-UUID `req`. The server assigns a real UUID when it has work.

> 📖 Polling selection rules (priority / TTL / created_at order): see [`mqtt-rpc-protocol.md §Polling`](./mqtt-rpc-protocol.md) and [`TTL.md`](./TTL.md).

```mermaid
sequenceDiagram
    autonumber
    participant S  as Server (Cloud Core)
    participant B  as MQTT Broker
    participant D  as Device (Client)

    loop req_poll_timer fires
        D ->> B : PUBLISH dev/<SN>/req [zero UUID]
        B ->> S : DELIVER req

        alt No task available
            Note over S: Server silently drops or ignores
        else Task available
            Note over S,D: corr = a1b2c3d4-... assigned by server
            S  ->> B : PUBLISH srv/<SN>/rsp [method=51]
            B  ->> D : DELIVER rsp

            Note over D: Execute task with payload.dt

            D  ->> B : PUBLISH dev/<SN>/res [status=200]
            B  ->> S : DELIVER res

            S  ->> B : PUBLISH srv/<SN>/cmt [result_id=67890]
            B  ->> D : DELIVER cmt
        end
    end
```

---

## 4. Fail-Fast Flow — Interactive Task Without Active WS (Sequence)

For `method_code` in range `3000..3999` or `0xFFFF`, the device **must** publish an immediate terminal `res` (status 500) if no active WebSocket client is available, preventing silent timeouts on the backend.

```mermaid
sequenceDiagram
    autonumber
    participant S  as Server (Cloud Core)
    participant B  as MQTT Broker
    participant D  as Device (Client)
    participant W  as WS Gateway (External)

    Note over S,D: corr = a1b2c3d4-..., method_code in 3000-3999 or 0xFFFF

    S  ->> B : PUBLISH srv/<SN>/tsk [method=3001]
    B  ->> D : DELIVER tsk

    D  ->> B : PUBLISH dev/<SN>/req
    B  ->> S : DELIVER req

    S  ->> B : PUBLISH srv/<SN>/rsp [method=3001]
    B  ->> D : DELIVER rsp

    Note over D: Check active_ws count

    alt active_ws == 0 OR task_start failed
        D  ->> B : PUBLISH dev/<SN>/res [status=500]
        B  ->> S : DELIVER res (fail-fast terminal)

        S  ->> B : PUBLISH srv/<SN>/cmt
        B  ->> D : DELIVER cmt
        Note over S,D: Backend receives explicit terminal state, no silent timeout
    else WS active AND task_start succeeded
        D  ->> W  : Forward task via WebSocket
        W  -->> D : Result from WS client

        D  ->> B : PUBLISH dev/<SN>/res [status=200]
        B  ->> S : DELIVER res

        S  ->> B : PUBLISH srv/<SN>/cmt
        B  ->> D : DELIVER cmt
    end
```

---

## 5. Async Event Flow — Device-to-Server (Sequence)

Events are independent of RPC. The device emits them at any time (timer-driven or internally triggered).

**Server-side processing:**
- Events are deduplicated by `(device_id, dev_event_id, dev_timestamp)` where `dev_event_id != 0`
- `dev_timestamp` accepts both **Unix epoch** (int/str) and **ISO 8601** strings
- EVA (acknowledgment) is sent for both new events and idempotent duplicates
- EVA payload: `{"status": "success"}` or `{"status": "error"}`
- EVA is sent only when `event_type_code != 0`, `dev_event_id != 0`, and event is not a gauge type

```mermaid
sequenceDiagram
    autonumber
    participant D  as Device (Client)
    participant B  as MQTT Broker
    participant S  as Server (Cloud Core)

    Note over D,S: Runs independently of any active RPC session

    loop healthcheck_timer fires OR internal event occurs
        D ->> B : PUBLISH dev/<SN>/evt [event_type=44, new UUID]
        B ->> S : DELIVER evt

        opt Server acknowledges (optional)
            S ->> B : PUBLISH srv/<SN>/eva [same corr]
            B ->> D : DELIVER eva
        end
    end
```

---

## 6. Topic Summary

```mermaid
flowchart LR
    subgraph dev ["Device to Broker (pub)"]
        REQ["dev/&lt;SN&gt;/req\nPoll or pick up task"]
        ACK["dev/&lt;SN&gt;/ack\nOptional delivery ACK"]
        RES["dev/&lt;SN&gt;/res\nTask result 200/4xx/500"]
        EVT["dev/&lt;SN&gt;/evt\nAsync event"]
    end

    subgraph srv ["Broker to Device (sub)"]
        TSK["srv/&lt;SN&gt;/tsk\nServer-initiated task"]
        RSP["srv/&lt;SN&gt;/rsp\nTask payload + method_code"]
        CMT["srv/&lt;SN&gt;/cmt\nResult commit / confirm"]
        EVA["srv/&lt;SN&gt;/eva\nEvent acknowledgement"]
    end

    REQ <-->|correlationData| RSP
    TSK -->|triggers| REQ
    ACK -.->|optional| TSK
    RES <-->|correlationData| CMT
    EVT <-->|correlationData| EVA
```

---

## 7. correlationData Lifecycle

```mermaid
flowchart LR
    Z["correlationData\n00000000-...\nzero UUID"] -->|Polling REQ| SRV_ASSIGN["Server assigns real UUID"]
    SRV_ASSIGN --> REAL["correlationData\na1b2c3d4-...\ntask UUID"]

    TRG["Server generates\nUUID for Trigger"] --> REAL

    REAL -->|tsk| DEVICE
    REAL -->|req| DEVICE
    REAL -->|rsp| DEVICE["Device"]
    REAL -->|res| SERVER["Server"]
    REAL -->|cmt| SERVER
    REAL -->|"ack (opt)"| SERVER

    style Z fill:#f0f0f0,stroke:#aaa
    style REAL fill:#d4edda,stroke:#28a745
```
