# Camera declared nominal cadence 0.3

Revision: `camera-cadence/0.3.0-proposed`; implementation candidate, not deployed
or accepted on hardware. Exact bundle: `l4-media/3.0.0`, `siplite-camera/1.4.0`,
`camera-cadence/0.3.0-proposed`, `camera-enrollment/0.5.0-proposed`,
`camera-ctl-monotonic/0.2.0-proposed`. Local/RPC configuration remains camera1.0.
Old schemas/packets and common media3 bytes remain unchanged.

## Declared FPS and actual delivery

Common media3 README50РІР‚вЂњ53 defines FPS as declared nominal/target, not exact
instantaneous or achieved rate. Actual delivery FPS is telemetry. This revision
removes our finite-window2%, unique-inferred-FPS,4/32second and cumulative-phase
admission gates. It does not replace them with another actual-rate threshold.
No history ring, mean rounding, forced FPS configuration or RTP rewriting exists.

The selected camera video SDP must freshly and explicitly declare nominal FPS,
bound to the same authenticated selected RTSP video track, source/path generation,
codec and physical camera. `a=framerate:20` is a recommended encoding rate, not
proof that actual delivery equals20FPS. An exact declared integer value1..120 maps
to common track.fps. Parsing a decimal that represents an exact integer is not
rounding; arbitrary fractional declarations are unavailable in this integer-domain
revision. Missing, invalid, ambiguous or conflicting explicit nominal metadata
means unknown/unavailable; never derive a replacement from measured mean,
Auto configuration fps=0, arrival rate or an incomplete codec timing clock.
Only media-level attributes of the SELECTED video track participate. Global, audio
and unselected media attributes are ignored. Equal normalized duplicate declarations
(e.g.20 and20.000) are accepted; any malformed selected declaration or conflicting
normalized value makes nominal unknown without breaking the RTSP transport.

Declared nominal FPS is immutable for the current descriptor/binding hash. A
changed explicit declaration ends that attempt; a change in actual delivery FPS
alone does not. Explicit20 with actual20.5 or variable positive cadence is allowed
when all separate bitstream/source/resource/authority checks pass. The common
integer1..120 schema is a parsing guard, not a promise of every supported format.

## Complete source proof and GOP

Use complete validated AUs, matching VPS/SPS/PPS/profile/level/geometry, repeated
parameter sets at random access, no B-frame reordering, correct original sequence
and positive timestamp order. RTP uint32 unwrap requires each positive consecutive
delta strictly below2^31; duplicate/backward/ambiguous wrap, missing/corrupt AU,
changed source/codec/geometry/parameter sets, arithmetic overflow or unsupported
resources fail closed. These checks do not quantify actual FPS or compare it to
the declared nominal value. Header/marker sightings, ACK, freshness and browser
decode remain distinct evidence.

READY requires ONE complete validated GOP bracketed by TWO verified IDR+PS
boundaries, plus valid explicit nominal metadata and all binding/bitstream checks.
There is no4second minimum and no32second delay. At startup report the observed
representable GOP interval as common keyframe_interval_ms=ceil(originalticks/90),
within250..5000ms. The exact representability boundaries are22410ticks→249ms
(PENDING),22411ticks→250ms (READY),450000ticks→5000ms (READY), and450001ticks→5001ms
(PENDING). No separate actual250millisecond lower bound is introduced. An initial interval not representable in that common integer
range stays PENDING and updates the verified keyframe boundary within the same
original30second budget; never clamp or invent a descriptor value. After READY
additional earlier or later fully validated IDR+PS boundaries are allowed. There
is NO actual GOP period,5second interval, maximum-learnedG0 or105% runtime
comparison. The common nominal startup field is not an achieved-GOP admission gate.

The new-mode caller has an original bounded30second local monotonic acquisition
I/O budget, including waiting for the first verified boundary. Equality expires.
No retry, poll, short GOP or metadata change resets that original deadline.
Previous parser modes retain their original deadlines and behavior. Transport
I/O watchdogs remain independent of FPS; they must not synthesize a target-rate
admission barrier. The cadence observer retains bounded proof state only; no
32KiB timestamp history is required.

## Authority and version selection

New exact1.4/0.3/0.5 selection requires fresh full enrollment/readiness. Keep old
packet bytes and separate cohorts; old/mixed0.4 messages cannot authorize0.5 even
with identical media hashes. Preserve source/MAC/port2/path generation, boot
retirement, durable issuer generation/epoch/floor/high-water, full offer challenge,
readiness nonce, exclusive5second wire exchange, R/I original deadlines and stable
camera media-clock identity. No new lease rule, full TTL from receipt, event,
method, desktopCTL2 command, pipeline, writer, gate or server epoch reset is added.

## Offline evidence boundary

The independent verifier exercises declaration parsing and complete-proof decision
vectors with synthetic already-validated AU facts. It must permit declared20 with
actual20.5 and variable rates, and reject missing/conflicting nominal declarations,
codec/geometry/PS changes, corrupt or incomplete AUs and B frames. These vectors
cannot prove real VCL parsing, RTSP authentication, port binding or hardware
acceptance; separate parser C tests, runtime/DB tests and explicit live acceptance
are required. No implementation artifact implies deployment or activation.
