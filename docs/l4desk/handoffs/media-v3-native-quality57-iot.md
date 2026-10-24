# IoT media contract 3.0.0 — native quality milestone 57

The coordinator-owned package is vendored in `contracts/l4-media-v3/`;
its schema is copied byte-for-byte. Its schema SHA-256 is
`b86ca6f066fcdecb09cf7145a7fb23d87b77311a53c7ea04f0fb6e8a905b2818`.
The package README defines the shared descriptor, native format and resource
rules. Frozen earlier schemas remain unchanged.

## HTTP selection

Use `X-L4-Media-Contract: l4-media/3.0.0` on the existing internal video
capabilities, stream/start, video-state and video-stop endpoints. Unknown
revisions, mixed camera/media selection and disagreement with the saved or
submitted descriptor are rejected with HTTP 422. Omitting this header never
selects v3, regardless of the dimensions. Legacy stream/start request bodies
cannot enter the selected v3 flow.

Capabilities still return `negotiated_v2` to identify the existing CTL2 transport,
plus `contract_version: 3` and `video_capabilities.contract_version: 3` on the
selected flow. State retains `version: 2` and adds `contract_version: 3`;
`descriptor` and `actual_descriptor` include their own version marker. CTL wire
commands, ACKs, events, MQTT topics, presence capability `video_contract_v2`,
lease operations, issuer-monotonic admission and clocks are unchanged. The new
native capability response explicitly identifies the media version.

The existing inventory query forwards source_id/profile_id. Cache applicability
includes the selected media version. A version change invalidates incompatible
capability/probe snapshots and pending selection; an old response cannot answer
the replacement query. Old unversioned capabilities are never relabelled as v3.
Successful probe memory is retained separately from current applicability while
encoder_busy is reported. Memory is not authority for START; fresh ready
capability, exact track/profile, identity, source, geometry, binding and lease
checks still apply. Reopening UI reuses a fresh compatible capability rather
than sending another hardware probe. Changed presence invalidates the snapshot.

Both `low` and `default` admit the exact declared track, including 3000x2000.
No raster or cadence is inferred from a profile. Parsing allows the common
schema bounds and codec levels; desktop/native admission also enforces the
8,294,400 pixel resource guard. A mismatch or unsupported mode is rejected
explicitly; v3 does not silently downgrade a declared HEVC track to H264.
READY must match the complete versioned descriptor. Bound renewal keeps CTL2
and the original stream, lease and descriptor identity.

## Verification and deployment

Tests cover HTTP inventory -> START -> READY/state for both policies at
3000x2000, CTL2 bound renewal, cache/version mismatch, explicit HTTP selection,
source/geometry/track mismatch, native resource guard, successful memory during
busy and rejection of START from that memory. The coordinator's portable
contract tests cover native/small/portrait dimensions and invalid codec facts.

Implementation is prepared on a new branch from origin/master. Production
has not been changed. Deployment waits for the user's signal after media stage
1 advertises v3. Build/publish through deploy/registry_app1.py on the dedicated
builder, then deploy only app1 by immutable SHA/digest. Record deployed revision,
digest, health and v3 inventory/state smoke in the external milestone handoff
before opening MenuBuilder stage 3. No live stream or competing svc_desk client
is started by this task. Camera gates/writers and firmware are unchanged.

Validation for this implementation:
- Full application suite: 866 passed, 7 skipped, 4 existing dependency warnings;
  an existing AsyncMock coroutine warning was also emitted during collection GC.
- Final video module: 157 passed, including four additional malformed-input/H264
  cases added after the full run. No application code changed after that run.
- Coordinator portable contract suite: 6 passed.
- Ruff and Black: all six changed application/test Python files pass.
  Repository-wide Ruff retains 14 existing findings and 8 style findings in the
  coordinator's unchanged portable test file; the imported package is not forked.
- Targeted regex secret scan of all 13 changed/new files: no findings.
- Git whitespace check passes. The staged schema's raw Git blob matches the
  coordinator's pinned SHA; imported README/test/schema attributes are retained.

## Cold-start addendum (IoT only)

For explicitly selected v3 desktop inventory, the command deadline, MQTT publish
TTL and pending/correlation window are 35 seconds. Desktop selection uses current
presence/inventory, with the initial unselected query using desktop availability.
Explicit camera/unknown sources and earlier media retain their 10-second inventory
budget. A live pending query remains authoritative beyond the old 30-second probe
cooldown; repeated UI reads cannot start a competing probe. Compatible fresh cache
and successful-probe memory paths return immediately without another command.

V3 desktop START accepts an issued-to-expiry interval up to 35 seconds. Its expiry
must still fit the submitted lease deadline and the actual publisher lease. A
shorter remaining lease therefore shortens the usable command window. Publication,
START waiting and READY admission all use this same immutable command deadline;
READY at or beyond the deadline is rejected. No lease TTL or contract schema/SHA
was changed. The native producer's separate 30-second hard bound is coordinator
scope; these tests simulate delayed replies and do not claim hardware acceptance.

Cold-start validation covers a correlated inventory reply after31 seconds, broker
TTL/correlation, pending-query reuse past30 seconds, immediate subsequent cache hit,
late inventory rejection, READY at34.999 seconds and rejection at35 seconds,
shorter20-second leases, >35-second rejection and preserved earlier/USB budgets.
Deployment remains pending the user's signal after media stage1.

Addendum checks: full application suite 883 passed, 7 skipped, 5 existing warnings;
13 new cold-start cases are included. Ruff/Black and whitespace checks pass.
The owner confirmed media stage1 ready and authorized app1 deployment on2026-10-24.
