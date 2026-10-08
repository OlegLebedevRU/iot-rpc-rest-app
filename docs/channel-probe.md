# Orphan transport-probe v1

Accepted 2026-10-08 for L4Update and future bounded channel diagnostics. This is
an explicit transport branch on existing MQTT topics, not a task or durable event.
It cannot execute RPC, consume queued tasks, change task state, publish billing or
webhooks, or create PostgreSQL rows. Device/active tenant lookup is read-only;
database identity lookup failure prevents success. Transport authorization remains
the broker's certificate-CN and device topic ACL. Payload cannot choose SN/tenant.

All four messages carry User Property `iot_probe=1`. Unknown marker values and
malformed marked messages are dropped without falling through to ordinary RPC or
event processing. Native correlationData remains mandatory, nonzero canonical UUID.

| Direction | Correlation | JSON body | Additional User Properties |
|---|---|---|---|
| dev/SN/req | fresh N | `{"v":1,"type":"channel_probe"}` | none |
| srv/SN/rsp | N | `{"v":1,"type":"channel_probe","status":"success"}` | method_code=0 |
| dev/SN/evt | fresh M, M!=N | `{"v":1,"type":"channel_probe","request_nonce":"N"}` | event_type_code=0, dev_event_id=nonzero uint32 |
| srv/SN/eva | M | `{"v":1,"type":"channel_probe","status":"success","request_nonce":"N"}` | event_type_code=0, matching dev_event_id |

The table's N is the actual UUID text, not the letter N. Body fields are exact;
extra/duplicate JSON fields, numeric-string version and oversized messages fail.
Valid CN-scoped messages receive generic `status=error` for unknown/unbound
identity or identity lookup failure; this reports that IoT answered while keeping
the barrier closed. Both RSP and EVA use the same exact fields for error; no tenant
or database detail is exposed. Invalid schema/marker and rate rejection are dropped.
Both replies
expire after 10 seconds and are not retained. Request body limit is 512 bytes.

Client requires RSP with matching N before generating M/EVT, then checks M, N,
event ID, marker, event code and successful EVA within a monotonic deadline. A
response from a previous stage/connection cannot satisfy a fresh barrier. Server
does not maintain a cross-worker session or prove that N was previously processed:
ordering and freshness are client gate requirements. Each reply authenticates the
routing SN's current registered device/active tenant binding independently.

Limits per application process: 64 marked messages per SN per 10 seconds, 128 per
second globally, at most 4096 live rate-limit identities. Entries expire in 10s;
new identities fail closed at capacity. Deployment totals scale with worker count.
Identity lookup is capped at 2s within a single 10s lookup-and-publish deadline.
Expired total budget produces no reply. This tests channel/handlers and identity lookup,
not durable event insertion or webhook delivery; use ordinary persistent events
when testing those guarantees. A downlevel server cannot satisfy the probe. No
automatic fallback may waive the required update communication barrier.

Implementation: `core/services/channel_probe.py`, `schemas/channel_probe.py`,
early dispatch in `topologys/fs_queues.py`; native consumer is l4con. No new MQTT
client connection or duplicated production client ID is used.
