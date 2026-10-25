# Camera measured nominal cadence adapter candidate

This candidate adds the explicit camera1.3/cadence0.2/enrollment0.4 selection to
the existing shared media3 camera adapter. It does not replace frozen camera1.2,
cadence0.1 or enrollment0.3 bytes or reinterpret an old message. No DB migration,
new MQTT/event method, new gate, media pipeline or descriptor extension is added.

Exact headers are media3, camera1.3, cadence0.2-proposed, enrollment0.4-proposed
and admission0.2-proposed. Partial or mixed bundles fail closed. Configuration
and RPC stay camera1.0/main_app. MEDIA receives common media3 header only; its
frozen schema and descriptor remain shared with desktop. R/I, stable media clock,
original START expiry, owner/session/SN/stream fences and TTL are unchanged.

The common descriptor cannot identify a camera adapter revision. START therefore
passes the validated HTTP selection explicitly to camera control and persists it
alongside the attempt, outside common media objects. State projects camera1.3 and
cadence0.2, retaining the same immutable media_clock_id. GET/STOP reject headers
that do not match the stored attempt. Legacy records without selection keep their
existing camera1.2 meaning; they do not silently upgrade to1.3.

Fresh gauge84 must contain a strict selected observation1.3. A fresh server
receipt cannot synthesize a missing track or convert an old observation1.2. The
new schema imports the common track, so no desktop20/30FPS geometry budget enters
camera1.3. Real producer resource/codec limits remain independent. FPS25/120 tests
prove schema/adapter behavior only, not hardware throughput support.

Enrollment0.4 retains the full-offer actor and durable counters. When configuration
or selection changes, completed enrollment responses are retired along with
pending/readiness/outbox; old0.3 proof cannot re-emit its cached commit in a0.4
configuration. Boot retirement, high-water and issuer authority are not reset.
An active stream still prevents reconfiguration. Every new selection requires
fresh full enrollment/readiness; no cross-version resume or renewed full TTL.

Owner observation packet is imported byte-exact from etranprocessing
eda95df3e311590141cfaaa53a4b51543882bed1, schemaSHA256
ed026e15251900f060b1a7550cb6e6f60c5c9631785979aef95fa11e713a446a.
Enrollment0.4 schemaSHA256
45ae401d6c16605a69c9823d4e76b4ca056c74664682c7fa31d03fc87d1d2bdf.
Exact file locks and immutable cadence/enrollment manifests are in contracts/.

Checks cover both codecs and low/default policies, common FPS20/25/120, mixed
revision and old proof replay, owner raw pins, strict HTTP/state models, real
controller outbox/cross-worker ACK, and PostgreSQL authority takeover/migration.
Offline policy vectors never replace original full-AU/GOP/PS/no-B validation.

No deploy or new advertisement is performed by preparing this candidate. A later
authorized app1 release MUST preserve the existing scoped camera activation
override: generic image-only deployer would omit that environment overlay. Capture
all current Compose files, append the new immutable image override last, recreate
only app1, verify unchanged existing gates/allowlist and all other container IDs,
and retain previous config/image for rollback. Firmware/browser acceptance remains
a separate coordinator stage after exact server/firmware revisions agree.
