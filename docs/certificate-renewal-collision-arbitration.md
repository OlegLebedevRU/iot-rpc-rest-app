# Certificate renewal collision arbitration

## Contract

The collision detector distinguishes the historical presence of two certificate
validities from a task-authorized sequential handover. No RPC/event codes or
payloads change. No PIN, CSR, credential or task payload is read by arbitration.

A rotation permit requires method7011 for the exact device, status LOCK (RSP
issued), an unexpired task, and creation/locked timestamps within the preceding
300 seconds. The creation bound prevents repeated REQ from extending the window.
READY/PENDING/deleted/expired tasks do not create a fresh permit. DONE is not
a general exception; the recovery rule below requires committed evidence.

To consume it, the incoming socket must appear in a complete, fresh RabbitMQ
Management snapshot for that SN. Its broker user, TLS flag, certificate validity
and CN/O/OU must match the candidate and previous tenant/device identity. Both
NotBefore and NotAfter must move forward and the new period must be valid now.
Another active certificate is never exempt, including on the same NAT address.
Missing/inconsistent broker evidence defers materialization without asserting a
security incident from historical data alone. No automatic unblock occurs.

The existing tb_persistent_variables table stores one server-owned bounded JSON record per
device (key renewal.collision.<device_id>): current validity, up to8 retired
validities, consumed task UUID and acceptance timestamp. Device and connection
row locks serialize decisions through the existing connection-state commit.
The task permits exactly one new generation. Returning to a retired certificate
is rejected even after restart or outside the detector's180-second history.
Reconciliation cannot erase this record. No schema migration is introduced.

RabbitMQ's per-user connections endpoint can return summaries without TLS
metadata. Missing detail is hydrated by exact connection name, never by a fallback
to another socket. Limit16 sockets,4 concurrent lookups,64KiB/response and4s total;
failure/closed socket is unknown, not an empty authoritative snapshot.

If the first connection event was deferred but the terminal already completed
renewal, recovery requires all of: DONE7011 plus stored200/applied, and event75
for this device/current tenant/SN with exactly the candidate NotAfter. The event
must have been received by the server after RSP lock and within300s of task
creation. Only tasks from the preceding24h are considered. Device timestamps or
a newly submitted inventory cannot extend that execution window. This recovers
the already evidenced generation; it never repeats RPC/PB operations or grants
an arbitrary later certificate. The same one-use/retired/concurrent-socket checks
apply. Changed generations in background reconciliation use this same arbiter,
with the per-device time budget checked and locks released promptly.

RabbitMQ currently exposes peer_cert_validity/subject to this detector; validity
is NOT a cryptographic fingerprint. The arbitration uses this existing broker
discriminator and the CA-authenticated TLS identity plus delivered task as its
trust boundary. It does not claim to verify PB's exact newly issued leaf serial
before connect. A future issuer-attested serial/fingerprint contract can tighten
this boundary; simply trusting a device inventory before TLS admission cannot.
Same-validity distinct certificates retain the limitations of broker metadata.

## RPC and event semantics

The permit means only connection handover admission. It is not proof of issuing
or installing a certificate and cannot mark7011 DONE. RES200/applied remains
produced by the terminal after credential validation/install; CMT acknowledges
durable server receipt. Event75 is produced by the terminal from its active
credential; storage/webhook/EVA semantics stay unchanged. PB confirms installation
through its existing authenticated inventory discovery, independently of the
collision decision. These confirmations cannot be prerequisites for the first
new-certificate MQTT connection: that would prevent their own delivery.

Duplicate connection events for the accepted generation are idempotent; worker
and app restarts use the durable record. A late event whose socket no longer
exists is deferred; existing connection.closed matching protects the new socket.
An old active socket plus the new certificate still follows the blocking path.
No IP whitelist or firmware sleep is introduced. Unexpected setup/re-enrollment
remains subject to existing provisioning policy; this exception is renew-only.

## Verification and release

Tests cover sequential rotation, overlap on same NAT, old-certificate replay,
one-use permits, new-task generation, missing broker snapshot, stale event,
foreign tenant/device identity, invalid TLS metadata, restart with stale telemetry,
strict bounded broker snapshots, and event-handler ALLOW/BLOCK/DEFER behavior.
Coverage includes real summary/detail shape, socket disappearing during lookup,
detail identity mismatch, deferred completed-task recovery, tenant-bound server
event timestamps and reconciliation ALLOW/BLOCK/DEFER.

Deploy only app1 from accepted origin/master via builder/registry immutable
digest. Preserve the full running Compose override chain and neighbor container
IDs. Existing blocks require operator resolution; installing the patch does not
clear incidents. Image rollback is schema-compatible and does not delete state.
