# Camera monotonic server runtime

The subsequent Native Auto1.1/enrollment0.2 implementation is documented in
[the bundle handoff](l4desk/handoffs/camera-native-auto11-iot-http.md).
It requires all four exact revision headers, adds a complete offer and upgrades
validated authority JSON to version2 without resetting fences or counters.
Both runtime gates remain off. The original implementation evidence below
describes the immutable PR141 baseline.

Server implementation of the reviewed enrollment and admission contracts, based
on `fdfa36862ecaa2c63f56ac2ff32b7e1d3d90b8c5` (merged PR139). This adds an optional
server path; it is not a camera firmware release, production deployment or real
4623 acceptance. The installed desktop/session lifecycle path is independent.

## Explicit negotiation and rollout

`APP_CONFIG__CAMERA__MONOTONIC_RUNTIME_ENABLED` defaults to false. It does not
enable camera RPC writes, change `writers_enabled` or expand the existing native
START SN allowlist. Those existing permission gates still apply at camera START.
No configuration file or production environment was changed for this work.

Both peers must implement these exact, independently negotiated revisions:

- `camera-enrollment/0.1.0-proposed`
- `camera-ctl-monotonic/0.2.0-proposed`

The reviewed names retain their `proposed` suffix; this implementation does not
silently rename or modify the pinned packages. Frozen desktop CTLv1/HEVC2.0 and
camera1.0.0 schemas remain unchanged. Unsupported/partial negotiation fails.
The desktop `issuer_monotonic_v1` marker is not camera enrollment authority.

Before enabling the server gate, migrate the database to `0013_camera_authority`,
deploy readers and obtain cross-owner firmware/BFF agreement on the bindings and
HTTP orchestration below. Enable native writers only under the separate release
gates and complete real-camera acceptance. There is no automatic fleet enablement.

## Durable authority and egress

`tb_camera_authorities`, keyed by the authenticated terminal SN, stores issuer
generation, enrolled/current and retired boot IDs, the admission counter,
authorized descriptor/binding, bounded request/result queues and command outbox.
There is no TTL on counters or retired boot identities. A missing/version-invalid
authority row fails closed; handlers never recreate it from hello/presence.

Migration0013 seeds existing devices and an INSERT trigger initializes genuinely
new device records. A device UPDATE/upsert cannot restore an erased authority
row. Authority rows are retained independently of device deletion; an INSERT
for an already known SN preserves its existing authority via ON CONFLICT rather
than resetting it. Existing device CRUD is not blocked by a new foreign key.
Retiring/renaming an SN requires explicit camera identity lifecycle handling.
Downgrade intentionally refuses to erase authority state. Roll back application
code after draining admissions; retain this additive table and its trigger.

Every worker can enqueue requests. PostgreSQL `SELECT FOR UPDATE` serializes
per-SN mutations. One process owns each issuer epoch, with a10-second renewable
database ownership fence. Its clock exports wall_ms0 + locally elapsed monotonic
milliseconds, never newly sampled UTC. Process identity is generated after fork.
The background worker scans at100ms intervals, at most256 candidates per scan;
requests also pump their own SN when they own it.

A takeover increments the durable generation and changes issuer epoch. It
invalidates pending enrollment, readiness, active attempts, old command receipts
and outbox, while preserving counter, binding and boot retirement. Old pending
monotonic timestamps are never interpreted in a successor process. Database wall
time governs owner availability only; a clock jump may fence an owner but cannot
extend a camera lease. The old terminal watchdog remains the final expiry if a
new enrollment cannot be delivered.

The state transition and outbound payload commit together before publication.
The egress transaction checks owner, epoch and deadline again and holds the row
fence through broker confirmation (bounded to2s). START/RENEW recheck current
Redis lease identity and active-key TTL; the lease hash's extra30s retention is
not budget. Network time is conservatively subtracted. A shortened/revoked lease
drops the old payload: decreasing MQTT TTL alone cannot repair its wire expiry.
Ambiguous publication retries the identical command/sequence until its original
deadline. STOP cancels unsent START/RENEW from the retired attempt.

Requests, recent results, recent enrollment IDs and command receipts are bounded
to64 entries. FIFO order is stored in arrays, not JSONB property order. Pending
enrollment/readiness each have a single original5000ms owner-monotonic budget.
Retired boot cap is65536 per SN; safe counters stop at9007199254740991, never wrap.
Eviction of response caches cannot reset any fence or admission counter.

## MQTT exchange

Only existing authenticated `dev/<SN>/ctl` and `srv/<SN>/ctl` are used. Payload SN
must match transport SN. The existing broker mTLS/ACL is the trust boundary; the
payload cannot select another device. No new RPC methods, MQTT evt or presence
lifecycle are introduced; RES/gauge84 and credential freshness are unchanged.

Hello/proof use native CorrelationData=enrollment_id; offers/commits echo it.
Readiness query/result use CorrelationData=readiness_nonce. Produced stream
commands keep CorrelationData=command_id. Application nonce/challenge checks
remain mandatory; MQTT PUBACK is not fresh readiness or physical completion.
New inbound messages reject duplicate keys, unknown fields, wrong revision,
oversized/deep JSON and non-v4 boot/enrollment UUIDs. Wire bounds are4096 bytes
and UUID spelling is canonical lowercase, preventing case aliases of retired boots.
JSON depth is limited to8. Legacy ACK/NACK shapes remain intact; matching command/lease/stream
IDs associate them with the enrolled boot/epoch. Safe receipts omit free-form
device diagnostic bodies.

An offer never retires the previously enrolled boot. Only the matching live proof
under the current fence commits retirement and installs a floor at least
max(offered floor, proof high-water, durable counter). Expired/duplicate pending
hello/proof cannot refresh the original budget. Recently completed proof can
replay only its exact commit within that same budget, without resetting state.
After recent enrollment-cache eviction a replayed hello may solicit a new server
challenge; an old proof cannot match it. It grants no authority by itself.

Readiness increments the durable per-boot admission counter before publication.
Its result must match exact nonce, counter, boot, epoch, physical binding and
descriptor. START requires that accepted unconsumed result explicitly; receipt
time or a cached capability is never an anchor. No terminal R is sent or trusted.
The terminal implements the immutable R/I mapping and its own strict watchdog.

START expiry remains lease expiry, with initial/renewal issuer intervalв‰¤60000ms.
STOP intervalв‰¤5000ms. Renewal sequence strictly advances; the initial issuer
coordinate is never rebased and later offsets may exceed60s. Expired/stopped
attempts cannot renew. A new attempt needs fresh readiness and lease/stream IDs;
when a negotiated attempt is retired by confirmation/failure/cleanup its parent
stream lease is revoked so that it cannot be reused. ACK and logical closure do
not prove RTP freshness, exact post-START descriptor or browser decode.

## BFF orchestration

All new endpoints are under `/api/internal/v1/remote-input` with the existing
internal service key and organization/device authorization. They require both:

```http
X-L4-Camera-Enrollment: camera-enrollment/0.1.0-proposed
X-L4-Camera-Admission: camera-ctl-monotonic/0.2.0-proposed
```

1. `POST /devices/{sn}/camera/admission/prepare`, body containing exactly
   `descriptor` and `physical_camera_mac`. Supply the complete negotiated camera
   descriptor, not a browser-authored digest. The server checks fresh online
   main_app gauge84, exact actual track, a ready discovery at physical port2 and
   the selected MAC's verified port/auth status. There is no raw camera mutation.
2. Firmware sends a genuine boot hello, accepts the fresh offer against its actual
   binding, returns proof and installs the matching commit. `GET
   /devices/{sn}/camera/admission` reports generation/epoch/boot/counter/enrolled
   for the authorized organization; it grants neither readiness nor a lease.
3. `POST /devices/{sn}/camera/admission/readiness` has no body. It rechecks the
   current physical observation, emits a new query and waits for its matching
   result. The returned query includes the nonce, admission sequence and original
   expiry. A timeout/failure is not permission to reuse the query.
4. Only after readiness create the lease budget/media attempt and POST the
   existing camera1.0.0 stream START with the two headers above plus
   `X-L4-Camera-Readiness: <returned nonce>`. The camera media body is unchanged.
   Retain `X-L4-Camera-Contract: siplite-camera/1.0.0` and existing lease/user/session
   headers. START reserves a held outbox entry; only successful lease/epoch
   reservation releases it. A command ACK is read from shared durable state,
   including when another app worker receives it.
5. Existing keepalive/STOP routes use the stored negotiated attempt to select
   RENEW/STOP. No legacy command is sent for that attempt. A configured monotonic
   camera START without explicit runtime headers is rejected while the gate is
   enabled. Failure does not fall back to another codec or start another stream.

The binding's `path_generation` is `port2/<discovery.generation>/<descriptor.geometry_generation>`.
Firmware must agree on that exact representation and hash the full binding,
including current boot. Descriptor/binding digests use the reviewed integer-domain
RFC8785 rules and canonical byte/hash vectors. A new physical camera, port/path
generation or descriptor requires re-preparation/enrollment and fresh readiness.
Cleanup also retires streams whose fresh observation, lease or issuer is invalid.

## Verification and remaining acceptance

Unit/integration checks cover strict MQTT correlation, wrong/stale proof,
floor preservation, original timeout boundary, retired boots, issuer takeover,
counter persistence, concurrent START, consumed readiness, cross-worker ACK,
long renewal offsets, STOP/replay, unsent START cancellation, shortened lease,
Redis active TTL, descriptor canonicalization and monotonic/UTC changes.

Real PostgreSQL18 tests ran on authorized builder176 in an isolated
`camera_runtime_test` database, with disposable schemas: row-lock concurrency,
rollback/persistence, actual0013 migration and trigger, and actor takeover with
old-owner egress rejection. The production database, running application
containers, RabbitMQ and nginx were not modified. The native terminal and MQTT
broker were substituted in tests; real4623 end-to-end video and firmware writer
acceptance remain separate required gates.

Reproduce PostgreSQL checks with `CAMERA_RUNTIME_TEST_DB_URL` pointing exclusively
to a dedicated database named `camera_runtime_test`, then run
`uv run pytest app-service/tests/core/services/test_camera_runtime_postgres.py -q`.
The tests create/drop only UUID-named temporary schemas in that database.

Validation on2026-10-24: full pytest with PostgreSQL tests enabled **883 passed,
7 skipped**,4 dependency warnings plus the pre-existing unawaited AsyncMock
warning. New runtime modules/tests pass Ruff; comparison of all changed Python
files with the base shows45 pre-existing Ruff diagnostics and no introduced
ones. Black passes all18 changed Python files. The original contract packages,
uv.lock and legacy camera producer are unchanged. The temporary176 PostgreSQL
container and local SSH tunnel were removed after verification.

## Owning worker lifetime

The monotonic camera issuer is process-owned. A real worker exit/restart still
invalidates its epoch and requires the existing durable takeover/enrollment;
original deadlines, counters, ownership fences and replay rules are unchanged.

When the existing `camera.monotonic_runtime_enabled` setting is true, the
`run_main` entrypoint selects Gunicorn `max_requests=0` and
`max_requests_jitter=0`. This disables only automatic HTTP-request-count recycling:
otherwise the previous 1000+0..100 policy deliberately kills a healthy owning
worker during an active camera stream. A production trace demonstrated that
exact failure: request limit1001 terminated the worker, its10second authority
heartbeat expired, and a legitimate successor cleared enrollment; keepalive
then failed with `camera_enrollment_required`. Extending TTL or keeping a dead
owner alive would bypass the intended fencing and does not fix that cause.

With the camera runtime disabled or the new function argument omitted, historical
1000/100 recycling remains. No new environment option or gate is introduced.
Intentional shutdown, crash, deployment and actual ownership loss continue to
end that authority; the change does not promise seamless streaming across restart.
