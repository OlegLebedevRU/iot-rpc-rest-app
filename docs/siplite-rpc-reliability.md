# Durable replay for configuration RPC49

Draft implementation contract for siplite reliability work. Firmware integration
and hardware acceptance are pending.

RPC49 remains an ESP32-local configuration transaction, ending in RES/CMT with
no new event. Existing configuration-cache reload remains unchanged. This does
not add an STM32 command or change the bus protocol. HTTP NVS requests without
an operation UUID remain outside MQTT replay protection.

Before applying records, the parser validates the envelope UUID, integral
created_at and the complete existing payload schema. It persists a receipt
containing task identity, method, payload fingerprint and an unfinished marker.
Storage failure prevents execution. After execution it persists the exact RES
body/status/result_uid before publishing any result. Lost PUBACK, CMT or a
duplicate RSP never authorizes another application of configuration records.

The storage transaction is separate from configuration application: writes to
multiple namespaces are not atomically rolled back. If reset or an ambiguous
storage failure leaves an unfinished receipt, the result is outcome_unknown
(500), with no automatic reapplication. The operator/server can read current
configuration and submit a new task UUID after reconciliation. Do not report
success for a possibly partial application. A final saved result is replayed
byte-for-byte with the same status and result_uid.

The fingerprint excludes delivery bookkeeping such as status/pending_at/locked_at.
It covers the method and normalized parsed payload. A changed payload under the
same task identity is rejected before any write. Sensitive configuration values
are not copied into the receipt; only a SHA256 fingerprint and bounded result
metadata are retained. Receipts must use a private NVS namespace excluded from
generic HTTP/MQTT reads and writes.

Use a small fixed receipt capacity and result size; no new worker or timer.
The parser owns storage, execution and retries. MQTT callbacks only enqueue a
bounded CMT notice. CMT must match the task UUID and result_uid and carry a valid
positive result_id before marking a final receipt acknowledged. PUBACK and
successful enqueue are not CMT. A full queue may drop a CMT notice safely:
the device republishes the unchanged result and the server acknowledges again.

Unacknowledged records are never evicted to admit more changing work. Exhaustion
rejects new work before side effects. After acknowledgment, a bounded receipt
window plus a persisted eviction watermark rejects unknown older task identities
instead of replaying effects after eviction. This deliberately favors avoiding
stale configuration over accepting arbitrarily old out-of-order tasks. Corrupt
journal/storage failure fails closed for changing RPC; local authenticated repair
must remain usable. Retries are paced and yield to current control work; offline
operation performs no repeated flash writes and never causes a reboot merely
because MQTT is absent.

Acceptance must cover every storage boundary (including writes persisted despite
an error return), reset between effects and final receipt, changed payload,
duplicate/lost CMT, storage-full/queue-full/OOM and restart with pending results.
This proposal does not claim to cover RPC19/411/512 completion events, per-item
RPC35 results, external UDP effects, camera/audio leases or all other methods.

