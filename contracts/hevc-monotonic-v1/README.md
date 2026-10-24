# hevc-monotonic/1.0 — admission without device UTC

Semantic extension of HEVC2.0 plus hevc-probe-memory/1.0. Frozen schemas are not
edited. Runtime capability validators use capabilities.schema.json from this
extension. New native agents advertise admission_clock="issuer_monotonic_v1".
Omitted means legacy admission; explicit null/false/unknown markers are invalid.
This marker alone grants no rights and does not authorize a stream.

## Capability / probe

The server owns query issued_at_ms, expires_at_ms and pending nonce. The device
uses only the duration expires-issued on its monotonic clock; no comparison
with device UTC. The server still rejects ACKs with expired/wrong nonce, SN,
source or server epoch. Work is bounded even for an old/replayed query; such a
query cannot authorize START without a currently accepted correlated response.

checked_at_ms = query.issued_at_ms + elapsed_between_local_query_receipt_and_check.
It is a conservative projection in the issuer's clock, not the device RTC and
not a claim of exact UTC measurement time. Snapshot expiry stays ≤60seconds.
New measurement dates use the same reference; dates are diagnostics only.
Persisted hardware facts remain reusable. Native cache v1 migrates to v2 without
new hardware probes: old device-UTC dates become unknown (measured_at_ms omitted).
If an issuer's date moves behind an earlier measurement, omit that date instead
of treating an otherwise valid hardware fact as unsupported.

## Fresh admission for a new desktop START

For a Windows disp: source advertising this marker, MB requests a fresh
applicability confirmation before constructing START. IoT refresh=true bypasses
the snapshot read cache/cooldown; it does not replace a live pending query.
Known native profiles answer from persistent memory, without activating encoder.
Legacy agents without the marker do not receive an extra forced probe.

Let R be the device monotonic tick of that exact applicability snapshot, and I
the issued_at_ms of its subsequent server START. R precedes START construction.
Store R and I only in RAM, bound to agent/capability/lease/stream/descriptor IDs.
They are local implementation fields, never supplied by a peer in the payload.

- Initial command deadline: R + (START.expires_at_ms - I).
- Initial lease deadline: R + (START.lease_expires_at_ms - I).
- Later command deadline: R + (command.expires_at_ms - I).
- Renewed lease deadline: R + (renew.lease_expires_at_ms - I).

Use only differences between timestamps from the same issuer. Command intervals
must be positive and ≤60000ms. Expiry is strict: now_tick >= deadline rejects.
The anchor precedes command construction, so this may expire conservatively
early; network/queue delay never starts another full budget on receipt.
An expired lease cannot be revived by renewal. Older/duplicate renewals do not
extend it; duplicate START does not reset the anchor or start another encoder.
Agent restart discards admission state; persisted codec support is not permission.
Source/profile, lease/scope/tenant, current epoch/geometry and descriptor checks
remain. The existing l4capture IPC already uses monotonic deadlines and is unchanged.

## Rollout and firmware boundary

Update IoT reader/refresh policy and MB marker-aware START first; then native.
New native requires these readers and fresh admission. Wire START/STOP/RENEW
fields are unchanged; this explicit extension changes their admission semantics.
Old native still needs its old time assumptions until upgraded.

This implementation changes Windows desktop CTL v2 only. Camera siplite CTL v1
producer/contract and firmware writers are NOT changed by this PR. Its current
START has issued_at_ms=server publication time and expires_at_ms=lease expiry;
STOP expires at publication+5000ms; CameraRenewCommand also carries ttl_sec=60.
Do not assume a new ttl_ms, lease_remaining_ms or anchor field was added there.

Firmware may adopt the principle only with an agreed correlated readiness anchor
preceding the server budget calculation. Starting an entire lease TTL when an
arbitrarily delayed START is received is not equivalent and is not safe admission.
Keep exact boot/lease/stream/descriptor identity, duplicate handling, no resurrection,
strict local expiry and timer wrap/reboot rules. Coordinate the camera handshake
and revision with its owner before advertising this marker on that path.

Conformance cases: vectors.json. Tests must cover device RTC ±days and jumps,
delayed commands, nonce/epoch mismatch, duplicates, renewal after expiry and boot.
