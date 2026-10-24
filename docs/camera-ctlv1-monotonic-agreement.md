# Camera CTLv1 monotonic admission — server proposal

Status: **proposed for coordinated review, not agreed or implemented**.
Date: 2026-10-24. Baseline: IoT
`b42e4844536e42de6b3347923125ccd260d97ca7`.
Review correction: supersedes the rejected0.1 candidate after firmware review.
Source task: `CAMERA-CTLV1-MONOTONIC-AGREEMENT.md` in the siplite task packet.
This is the IoT deliverable for step 1: explicit wire proposal, ownership,
ordering, clock epoch, retention and executable delayed-delivery vectors.
No deployment, camera marker advertisement, firmware writer enablement or
allowlist expansion is authorized. Existing CTLv1 and frozen packages stay intact.

## Explicit extension and ownership

Proposed revision: `camera-ctl-monotonic/0.2.0-proposed`, carried in required
`camera_admission_revision` on every message. The candidate schema and offline
oracle are in [contracts/camera-ctl-monotonic-v1](../contracts/camera-ctl-monotonic-v1/README.md).
`v=1` denotes the CTL envelope; it does not make the extension legacy compatible.
Strict legacy parsers must reject these fields. Both peers must explicitly
negotiate this exact revision before using it; cached camera capabilities and
the desktop `issuer_monotonic_v1` marker do not negotiate it.

IoT owns the cryptographically random UUIDv4 readiness nonce, pending state,
authenticated SN/boot association, issuer epoch, sequence allocation, lease and
command production. MenuBuilder requests fresh readiness before media lease
budget/START construction. Siplite owns boot identity, physical camera/path
observations, RAM anchor, token consumption, watchdog and replay protection.
Media owns the immutable concrete descriptor; IoT obtains its SHA-256 from the
trusted prepared descriptor, never from an untrusted browser assertion.
The digest is SHA-256 of [RFC8785](https://www.rfc-editor.org/rfc/rfc8785)
canonical UTF-8 descriptor JSON, without BOM or trailing newline. Peers verify
that exact negotiated descriptor, including source and codec. Descriptor numbers
in this candidate are integer tokens in the safe IEEE754 integer range
[-9007199254740991,9007199254740991]; fractional/exponent tokens are rejected
before hashing, even20.0. This deliberately restricts the serializer to the
integer domain of the camera descriptor, not general JCS floating-point support.
No defaults, omitted fields or Unicode normalization are inserted before hashing.
Keys sort recursively by UTF-16 code units; array order is preserved. cJSON
print order and Python sort_keys alone are insufficient for general Unicode keys.

[Hash vectors](../contracts/camera-ctl-monotonic-v1/descriptor-hash-vectors.json)
include native H.265 and H.264 descriptors, reordered equivalent input,
UTF-16 ordering, non-normalized Unicode, string escapes, negative zero and safe
integer boundaries. Each supplies input JSON, canonical JSON, exact UTF-8 hex
and SHA-256 for firmware/C++/Python/JavaScript consumers. Serialization probes
are labelled separately from media descriptors. Duplicate keys, lone surrogates,
unsafe integers and unsupported numeric tokens have explicit rejection vectors.
Expected bytes were generated independently with the rfc8785 Python package;
the local oracle implements only the stated integer subset.

## Fresh readiness

Proposed transport is existing authenticated `srv/<SN>/ctl` → `dev/<SN>/ctl`,
QoS1, retain=false. New discriminators are `camera_readiness_query` and
`camera_readiness_result`; they are control messages, not MQTT evt or new RPC
method codes. Existing RPC operations retain correlated `/res` and gauge84.
RPC correlation data remains mandatory and is separate from this readiness nonce.

Query carries nonce, **admission_seq**, issuer epoch, expected current boot, SN, camera source,
physical MAC identity, port/path generation, concrete codec and descriptor hash.
These fields form the immutable `binding` object repeated by result and commands.
Only one pending readiness per SN is allowed. IoT stores an authenticated pending
record **before** publication, with server monotonic timeout5000ms. The sequence
is allocated durably by a fenced counter keyed by (SN, terminal boot), strictly
increasing even across issuer epoch changes; gaps are legal. Query/result/START/
RENEW/STOP repeat the same admission_seq. It is not an issuer-local sequence.
Only authenticated boot enrollment may reset that counter for a new boot ID.
A query retry
keeps the same nonce/body and original timeout. Unknown/mismatched/stale result,
wrong transport SN or non-current boot cannot complete pending state.

Siplite validates the authenticated query and actual binding under its camera
guard. Immediately before first result emission it records R=monotonic_ms in RAM,
with a local readiness deadline R+5000ms. No R is sent on the wire. Device
accepts a new query only with admission_seq above its RAM admission high-water
mark and no active stream; it burns that sequence before recording R. One new
query replaces the previous unused token. The mark survives STOP, expiry,
encoder failure, binding invalidation, cache eviction and issuer restart.
Duplicate query in the recent cache returns its original result, with no new R;
same cached sequence with different content is conflict. After eviction,
sequence<=high-water is stale_admission, never a new token. A cached historical
ready response carries no renewed admission permission. Capabilities, result receipt
time and caller-supplied ticks never substitute for this observation.

IoT accepts result only while its original pending timeout is live, atomically
marks it accepted once, rechecks binding and authority, and only then constructs
START and its budget. A lost result requires a fresh nonce; a cached result is
never reused for another START. Readiness grants no lease and starts no encoder.

## START, renewal and STOP

START keeps current CTLv1 `mode=usb-camera`, `profile=default`, command/lease/SN/
stream IDs and issued/expiry fields. Added fields are revision, binding,
readiness_nonce, admission_seq, issuer_epoch and command_seq. START sequence is1. Lease/stream
IDs are fresh per attempt. The nonce explicitly identifies the exact readiness
result. `expires_at_ms` is still **lease expiry**, with positive interval at most
60000ms. There is no desktop `lease_expires_at_ms` field in this extension.

Under the same device guard, validate readiness and current binding, bind
I=START.issued_at_ms to R, lease and stream, check arithmetic and deadline,
consume the token, then start the encoder once. At now>=R+5000 reject unused
readiness even if the lease deadline would still be live. Rejected START cannot
be turned into a new attempt by retrying its nonce. Encoder failure ends this
attempt. No queue/network delay grants a fresh budget on receipt.

| Operation | Deadline in terminal monotonic milliseconds |
| --- | --- |
| START / initial lease | R + (START.expires_at_ms - I) |
| RENEW / replacement lease | R + (renew.expires_at_ms - I) |
| STOP command admission | R + (stop.expires_at_ms - I) |

Every later command repeats the binding, nonce, admission sequence, issuer epoch, lease and stream.
Each command's own expires-issued interval is positive, ≤60000ms for renewal,
≤5000ms for STOP. Renewal retains `ttl_sec=60` for CTLv1 shape only; it never
starts a60s timer. The offset from initial I can exceed60000ms for a long stream.
Require issued>=I, and nondecreasing issued values in accepted sequence order.
Use unsigned64-bit monotonic ticks, checked subtraction/addition and reject
overflow, underflow or counter regression. The active R/I pair never changes.

IoT allocates increasing command_seq atomically per stream across workers.
Renewal applies only when sequence>last accepted, current lease is still live,
mapped command deadline is live and the new deadline strictly exceeds the old
one. Cache policy below determines whether a duplicate returns a recent saved
result or a stale rejection. Command sequence high-water advances before effects
and never decreases, including on a nonextending renewal. Duplicate/older
sequence cannot extend a lease. The server never reuses command IDs or sequence
numbers within an admission; a new attempt has new lease/stream/command IDs.
STOP uses the same ordering rule; accepted STOP immediately terminates and
retires that admission, discarding its active R/I without disabling later admissions. Watchdog expiry wins at equality, including concurrent
renewal. Identity/path/descriptor invalidation terminates admission and requires
a fresh higher-sequence readiness and manual START; runtime failure cannot select another codec.
There is no positive grace period.

## Stable issuer coordinate system

Proposed server implementation captures wall_ms0 and monotonic_ms0 once per
issuer epoch, then exports issued=wall_ms0+(monotonic_now-monotonic_ms0).
Expiry is expressed in that same coordinate, not newly sampled UTC. Workers must
share a fenced authoritative clock/sequence owner; independent worker clocks
are forbidden. The owner measures budgets against monotonic time, capped by
remaining authoritative lease, rather than copying a UTC lease timestamp into
this coordinate after a clock jump. Wall-clock changes therefore cannot move
an active deadline. Device RTC is never consulted for admission.

Owner restart, monotonic regression, lost fencing or inability to preserve the
coordinate invalidates issuer_epoch, all pending tokens and active admissions;
renewal under a replacement epoch fails closed. Terminal still enforces the
old local watchdog if invalidation cannot be delivered. A replacement epoch
requires a fenced authenticated epoch transition on the terminal, then fresh
higher-admission-sequence readiness and new lease/stream IDs. Terminal never
adopts a new epoch merely because a query/START says so. Server restores its
counter from durable storage; neither server nor terminal high-water resets
on epoch change. Lost counter/fencing state fails closed until restored, or a
separately authorized genuinely new terminal boot is enrolled. Do not merely
switch epochs in a live lease. Existing UTC credential-envelope freshness is
a separate unchanged contract.

## Retention and bounded memory

No whole-boot receipt/tombstone table is required. Per terminal, each peer keeps
one admission high-water integer, one current token (at most5000ms), one current
stream with command high-water, and bounded recent readiness and command-result
FIFO caches, proposed64 entries each. Maximum message size4096 UTF-8 bytes and
depth8 bound cached content too. A receipt may store canonical content hash and
bounded result instead of its whole body. The offline oracle stores whole bodies
and tests with only four entries in each cache. Storage is O(cache capacity),
independent of uptime, renewal count and attempt count. Filling a cache evicts
its oldest completed receipt, never stops a stream or requires reboot.

An identical command_id/body in the recent cache returns **replay of the saved
historical result**, including duplicate STOP after retirement. Changed body
under that cached ID is conflict. Cache replay never executes, restores R/I,
extends a deadline or asserts that a formerly started stream is running now.
It is allowed after lease expiry if authenticated boot/epoch/binding still match.
After eviction, old admission sequences are stale_admission; within the active
admission, old command sequences and consumed START are stale_command. After
retirement the high-water still blocks recreating that admission. New readiness
with a higher sequence may authorize an independent attempt on the same terminal.
This replaces0.1's promise of exact result retention for the entire boot.

Readiness cache replays likewise never restore a consumed or expired token.
STOP, expiry and encoder failure retire only the current attempt, not the
terminal. A binding change requires explicit authenticated rebind before fresh
readiness; older binding traffic is rejected even when a receipt is cached.
Issuer epoch transition preserves both admission counters and rejects old-epoch
traffic. Delayed packets cannot change the current binding, issuer or boot.

A genuine terminal reboot generates an unpredictable new UUIDv4 boot ID before
accepting commands; RAM anchors, marks and recent caches may then reset under
that new identity. Server boot retirement/enrollment must be authenticated and
fenced, not inferred from a replayed presence/query/result. Old boot traffic never
resets counters or becomes current again. Monotonic regression fails closed until
a real new boot/clock epoch with fresh boot identity is enrolled. Wire sequences
are positive safe integers up to9007199254740991; wrap is forbidden. Exhaustion
of that protocol domain fails closed rather than resetting within the same boot;
this is separate from ordinary cache eviction and cannot occur at operational
renewal rates. No automated reboot recovery is introduced.

## Review and acceptance gates

IoT, MenuBuilder, media and siplite owners must accept the revision, wire fields,
descriptor digest, clock owner, durable admission counter,5s/60s limits, cache policy and boot retirement rules
before runtime implementation. These are concrete proposed choices, not claims
of cross-repository agreement. Then implement IoT reader/nonce/producer and MB
fresh orchestration, followed by firmware parser/anchor/watchdog/dedup and only
then marker advertisement under the existing release gates.

Offline vectors cover delayed/boundary START, UTC offsets/jumps, pending timeout,
wrong nonce/boot/epoch, duplicate START, reordered renewals, long streams, STOP
replay, expired lease, overflow and binding invalidation. They are an executable
reference, not evidence that product handlers implement the proposal. Terminal
4623 acceptance still requires the real camera/video with these cases; Windows
producer is unnecessary. Record immutable build SHAs, deployment evidence and
real decode separately. Existing RES/gauge84 and writer gates remain in force.

## Review reproduction and corrected evidence

[review-reproduction.json](../contracts/camera-ctl-monotonic-v1/review-reproduction.json)
records the0.1 defects before correction: the4096th renewal returns capacity;
a second START after STOP returns closed, as does an immediate duplicate STOP.
The revised model preserves one instance across independent attempts and tests
retirement by STOP, expiry and encoder failure; path/descriptor/camera rebind;
issuer restart with continuing sequence; new boot and rejection of old traffic.
The verifier additionally performs10000 renewals followed by10000 new START/STOP
attempts on that same instance, with four-entry caches, and checks stale traffic
after eviction and across issuer epoch transition. Evidence is generated by the
offline verifier, not production handlers; real terminal acceptance remains open.
