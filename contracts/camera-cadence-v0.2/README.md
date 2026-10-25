# Camera measured nominal cadence — joint-review draft

Status: proposal only, NOT agreed, implemented, negotiated, deployed or activated.
No frozen schema or production setting is modified by this review. Existing
cadence0.1 rejection remains correct. Original camera Auto configuration and RTP
timestamps are mandatory. Source: common media3 README defines FPS as declared
nominal/target cadence and actual FPS as telemetry; camera admission policy is
separate. No common media descriptor fork or MEDIA pipeline change is proposed.

## Candidate exact selection and revision ownership

```
X-L4-Media-Contract: l4-media/3.0.0
X-L4-Camera-Contract: siplite-camera/1.3.0
X-L4-Camera-Cadence: camera-cadence/0.2.0-proposed
X-L4-Camera-Enrollment: camera-enrollment/0.4.0-proposed
X-L4-Camera-Admission: camera-ctl-monotonic/0.2.0-proposed
```

The old observation1.2 schema hardcodes camera1.2/cadence0.1/enrollment0.3 in
capabilities and observations. Enrollment0.3 hardcodes those selections in HELLO,
OFFER, PROOF and COMMIT. Therefore new1.3/0.4 immutable packets are necessary;
editing old constants or advertising new behavior beneath old revisions is wrong.
MEDIA3 and CTLv1 admission0.2 do not hardcode these camera cadence revisions, so
their frozen schema bytes/hashes stay unchanged. Configuration/RPC remains1.0.

New1.3 retains the old observation shape and common actual_track ref, changing
only explicit revision constants/capability lists. No new telemetry/hint fields,
metadata reader or general options framework is in this revision's scope. Measured
rational rate is not inserted into common track.fps. Existing diagnostics may
continue reporting actual delivery independently of the immutable descriptor.

## Proposed measured nominal policy (numbers require joint acceptance)

Prerequisites remain complete validated VCL AUs, correct SPS/VPS/PPS and full GOP
proof, repeated parameter sets at random-access boundaries, no B-frame ordering,
authenticated physical camera/source binding and unchanged codec/geometry/path.
Markers, packet arrival, SDP alone, config fps=0, mean rounding and browser decode
cannot replace those proofs. Continuous failures revoke the current proof/session.

Candidate nominal F ranges1..120, matching common parsing bounds. There are no
desktop20/30FPS or resolution-based cadence budgets in this camera policy.
Independent actual producer resource/profile/raster limits still apply; schema
acceptance is not a claim a terminal supports120FPS at every geometry.

Unwrap each original uint32 RTP timestamp using consecutive positive deltas
strictly below2^31. Duplicate, backward, ambiguous-wrap, corrupt/missing AU or
checked arithmetic overflow fails closed. For each candidate F and complete AU
interval d ticks require 45000 <= F*d <=180000 (0.5..2 nominal frame periods).

For EVERY AU after four RTP seconds from the initial validated boundary, choose
the latest earlier AU whose timestamp is at least360000 ticks behind the new AU.
Let D be that original RTP span and N the exact number of AU intervals. Require:

`100 * abs(90000*N - F*D) <= 2*F*D`.

This is an explicit ±2% achieved-rate window policy, not RTP's inherent promise.
No first-anchor cumulative phase lattice is retained: bounded sustained20.3FPS
may qualify as nominal20, while unsupported sustained drift/ambiguous candidates
does not. Every overlapping four-second window is checked, not selected favorable
blocks or whole-session means. Candidate F becomes immutable before START.

Exactly one candidate must survive. Never pick nearest/lower/preferred F from
several survivors. For example
100FPS admits99/100/101/102 in this tolerance; unavailable is the safe result
in this revision. Independently verified nominal declarations are a possible
FUTURE extension, not implemented or accepted by0.2. No metadata/hint reader is
added. fps=0, user quality policy, rounded mean, packet arrival and SDP do not
resolve ambiguity.

GOP reference G0 is the MAXIMUM original tick span of all complete validated GOPs
at the first acquisition point satisfying the full initial proof. Require
22500<=G0<=450000 ticks for a representable250..5000ms nominal interval. Common
keyframe_interval_ms is ceil milliseconds: `(G0+89)//90`. Freeze original G0 and
that descriptor field at READY, never learn a larger reference after READY.
Every later complete GOP G requires positive order, G<=450000 and
`100*G <=105*G0`. A shorter FULLY validated random-access interval with repeated
PS and no B frames is allowed, including an extra interval shorter than250ms.
Earlier usable decoder-entry points can be requested by another RTSP client and
do not independently establish a source/codec change. Header/marker sightings
alone cannot establish such an exception. Source/PS/geometry/ordering changes
still revoke normally. This asymmetric rule is a new explicit camera policy;
common schema is not claimed to define an exact/maximum actual GOP duration.

Initial proof needs four RTP seconds plus two complete validated GOPs/third
boundary. Evaluate READY at a complete validated GOP boundary: the first such
boundary satisfying the window, unique-candidate and full-bitstream conditions
freezes F and the maximum of all completed acquisition GOP spans as G0. A boundary
with ambiguous candidates cannot reset the acquisition origin or deadline.
Waiting for the first complete random-access boundary counts toward
the original10second local monotonic acquisition budget and10RTP-second window.
Local elapsed>=10000ms or original RTP span>=900000ticks before proof is expired;
equality is not a fresh budget. Acquisition never slides its starting deadline.
Candidates that fail measured bounds do not reappear through resetting anchors.
After START the same F and G0 continue, with overlapping-window checks on every AU.
No FPS correction, codec fallback, timestamp rewrite, forced encoder FPS, silent
new attempt or reacquisition in place. Losing proof ends the immutable attempt.

## Bounded implementation requirements

Use1024 original extended uint64 timestamp slots (8192bytes), ring indices/count,
at most121 candidate bits/flags, current nominal and original GOP reference,
existing bounded bitstream/GOP/PS state. No unbounded timestamp history.
With F<=120 the per-AU minimum positive delta is375ticks; four seconds therefore
contains at most961 timestamp points, plus one predecessor.1024 slots suffice;
overflow or no trustworthy retained predecessor is a rejection, never eviction
of evidence needed to pass. Runtime can narrow to the single immutable candidate
after startup. The offline review oracle retains history for diagnosis only.
Before every sum, product, count/index increment or unwrap accumulation check
signed64 bounds; no saturating arithmetic that turns failure into success.

## Boot/issuer/lease protections explicitly preserved

Keep descriptor SHA256, physical MAC/path generation, boot retirement/high-water,
issuer epoch/generation, full offer challenge/floor, readiness nonce, exclusive5s
exchange/readiness windows, R/I admission and stable camera media clock unchanged.
Selection changes require a fresh full enrollment and readiness; they are not an
in-place reinterpretation of an old offer or running descriptor. Delayed/replayed
0.3 packets cannot authorize0.4 even if descriptor/binding hashes happen to match.
Existing durable counters/retired identities are retained across selection change;
no default-state reconstruction or new TTL from receipt. START/RENEW/STOP remain
camera CTLv1 admission0.2, including historical profile default adapter token.

## Executable review observations and adversarial vectors

verify.py / results.json are timestamp-only
policy experiments, not parser/runtime/hardware tests. Exact20, bounded20.3,
25 without desktop geometry cap and uint32 wrap yield single candidates. Short
prefix, duplicate/backward timestamps and1second stall reject.29.5 and undeclared
100FPS are ambiguous and must not admit. Additional short fully validated GOPs
do not independently revoke. Growth beyond the frozen upper bound rejects.

The256-marker real host diagnostic gives a unique four-second FPS candidate20,
and IRAP HEADER indices include0,20,...240,250. Under the asymmetric policy the
extra shorter interval does not eliminate nominal20 IF full validation later
proves the extra IDR+PS boundary; the timestamp/header hypothesis yields20.
Marker/header facts do not prove actual VCL/GOP completeness, physical port2 or
firmware acceptance. Root must inspect full validated original RTP; admission
remainsfalse in these diagnostic results.

Executable review vectors additionally cover a whole-session mean20 hiding eight
seconds21 then19 (reject), exact rate/GOP/AU threshold equality and one-tick
failure, half-range ambiguous wrap, checked64 overflow, all1024 ring starting
alignments,40seconds of minimum375tick increments with ring peak961points,
acquisition local/RTP deadline equality, nonboundary/incomplete-GOP rejection,
explicit AU/PS/no-B proof-gate failures, later growth above5000ms despite being
within105% of G0, and post-START rate change with no anchor reset. Proof-gate flags
test policy decisions, not actual VCL parser conformance; later C bitstream tests
must establish that real full AU/GOP/PS/no-B parsing supplies those facts.
An online delayed-uniqueness vector begins ambiguous29.5, resolves29 only at GOP
boundary155 after a larger acquisition GOP, and verifies G0 freezes at that real
boundary rather than the earlier ambiguous boundary120. Pending RTP/local10s
equality rejects; READY just before that original deadline passes. The timestamp
oracle without GOP/monotonic inputs is a cadence diagnostic only, never admission.
Run canonical cross-language C/Python vectors and all enrollment/replay/lease
regressions with the new exact revisions. No runtime/deploy/gate follows until
coordinator accepts the joint proposal and owner packets/hashes.
