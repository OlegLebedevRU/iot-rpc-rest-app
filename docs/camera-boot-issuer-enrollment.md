# Camera boot enrollment and issuer fencing — review proposal

Server implementation and rollout instructions: [camera monotonic runtime](camera-monotonic-runtime.md).
It is disabled by default; firmware negotiation and real terminal acceptance
remain separate from the reviewed proposal/model.

Revision `camera-enrollment/0.1.0-proposed`, extending the reviewed PR136
`camera-ctl-monotonic/0.2.0-proposed` without modifying its published bytes.
Specification/offline vectors only. No runtime handlers, firmware advertisement,
camera writers, allowlist enablement or STM32 operations are introduced here.

## Inspected transport and missing exchange

Current `core/camera/producer.py` emits legacy CTLv1 START/STOP/RENEW through the
authenticated control publisher. `remote_input/mqtt_bridge.py` takes SN from the
routing key and checks payload identity. Current camera capability/presence and
command ACK do not prove a fresh boot or an issuer transition. Their existing
handlers cannot implement the out-of-band reboot/rebind actions of the PR136
oracle. Therefore propose an explicit control exchange, not authority inferred
from a presence, self-declared boot/epoch, or a capability marker alone.

MQTT remains main_app: device→server `dev/<SN>/ctl`, server→device `srv/<SN>/ctl`,
QoS1, retain=false. No evt, RPC method or presence lifecycle changes. Broker mTLS
identity and topic ACL bind the terminal to SN; only the trusted server publisher
may send srv control. Payload SN must equal transport SN. CorrelationData is the
enrollment_id UUID on all four messages. Application also checks exact payload
correlation; broker delivery alone is not proof. Credential-envelope UTC validity
is separate and unchanged.

## Four-message exchange

Strict definitions and examples: `contracts/camera-enrollment-proposal/schema.json`
and `verify.py`. Max4096 UTF-8 bytes, depth8, reject duplicates/unknown fields.

binding_hash is lowercase SHA256 of canonical UTF-8 JSON of the complete PR136
binding object (boot_id, source_id, physical_camera_mac, path_generation, codec,
descriptor_sha256), using its already specified integer-domain JCS rules. The
server supplies an authorized expected binding; firmware recomputes it from the
actual local attachment/observation. Matching a self-declared digest alone is not
physical identity proof.

1. **hello**, device→server: genuine current boot_id UUIDv4, fresh enrollment_id
   UUIDv4 (device challenge), supported enrollment/CTL revisions, device admission
   high-water. The terminal retains one pending exchange and its local start tick.
   It never answers a hello on behalf of a different boot. Server hello processing
   creates pending state only; it does not retire the currently enrolled boot.
2. **offer**, server→device: echo SN/boot/enrollment, selected revisions,
   server challenge UUIDv4, durable issuer_generation, issuer_epoch UUID,
   approved physical binding hash and admission_floor. Server must durably store
   this exact pending exchange under its current fenced owner before publication.
3. **proof**, device→server: echo the complete offer and device high-water.
   Accept offer only for the live local challenge, supported revisions, current
   actual camera/path binding and nondecreasing issuer_generation. For the same
   generation the epoch must match. An epoch/binding transition first stops the
   old attempt and discards readiness. Preserve admission high-water. While
   awaiting commit no START is admitted. A new offer cannot refresh the deadline.
4. **commit**, server→device: echo the accepted offer/proof, with admission_floor
   raised to max(durable counter, proof high-water, offered floor). In one durable
   transaction check pending identity, deadline and current owner generation,
   retire the previous boot if different, install the new binding/epoch and floor,
   then publish. Terminal installs only the commit matching its pending proof
   before local expiry. It raises (never lowers) high-water to committed floor.
   Terminal independently rejects committed floor below the accepted offer's
   admission_floor or its current/proof high-water, even when all other echoed
   fields match. A rejection preserves the pending exchange, high-water and
   issuer state; a corrected commit can still complete within the same original
   budget. Rejected commits and duplicate offers never restart that budget.
   The durable server counter is a server-side obligation, not a value the
   terminal can independently observe.
   Fresh readiness with a strictly higher sequence is still required for START.

Server and device each bound the entire exchange by5000ms on their own monotonic
clock; no subtraction between clocks. Duplicate messages replay exact content and
original pending budget, never restart it. Lost/expired commit permits a new
hello from the same genuine boot; same-boot re-enrollment preserves all counters.
A repeated completed commit may be acknowledged locally as duplicate but cannot
restore old state, a readiness anchor, or a lease.

## Durable ownership and restart

There is one fenced issuer owner per SN. Acquire ownership with a durable strictly
increasing issuer_generation; issuer_epoch identifies that owner's monotonic
clock lifetime. A process/clock restart obtains a new generation/epoch. Workers
may serve REST, but all sequence allocation and control publication go through
the current owner. A transactional outbox carries generation; the single trusted
egress checks it against durable ownership before publication. Old in-flight
messages are additionally rejected by device generation/epoch and correlation.
Implementing this owner/outbox is the subsequent runtime task, not this proposal.

Durable state: current/retired boot identities, current issuer fence, physical
binding, per-boot admission counter, pending enrollment and committed receipt.
Boot tombstones remain durable for the credential identity lifetime; TTL expiry
must not make an old boot enrollable again. This is one record per genuine reboot,
not per renew/attempt. Set an explicit provisioned cap (proposed65536 retired boots
per terminal); exhaustion fails closed and requires operator identity lifecycle
maintenance, never silently evicts a tombstone. Pending exchange is one per SN;
recent response cache64 entries, completed-cache eviction does not remove fences.

Device RAM: current boot, pending exchange, accepted issuer generation/epoch,
binding and admission high-water plus existing bounded receipt caches. High-water
survives STOP, failure, rebind, enrollment retries and issuer transitions within
this boot. Only a genuine process/device boot with new unpredictable boot identity
resets it, and that identity must complete enrollment. Replayed old hello can
at most solicit an offer; the current terminal cannot prove the retired boot.
Retired-boot hello/proof are rejected before commit. Higher self-declared sequence
can only tighten the floor; it never confers lease/START authority.

After server restart, old pending exchanges are invalidated under the new owner;
old monotonic timestamps are never persisted as portable deadlines. Committed
boot/counters/fences persist. Loss/rollback of durable sequence or boot retirement
state is fail-closed; operator recovery must not silently reset it. Safe integer
domain≤9007199254740991; reject overflow, no wrap. New owner must fence the old
publisher before accepting proofs. A late proof/commit cannot roll back generation.

## Handoff and boundaries

Positive transcript: current boot hello → same challenge offer → matching actual
binding proof → durable commit → fresh readiness → START under PR136 semantics.
Negative transcripts: replayed retired boot; wrong transport SN; stale challenge;
late proof/commit; lost pending on restart; older issuer generation; changed epoch
at same generation; binding mismatch; unsupported revision; counter rollback.
The offline verifier exercises these transitions, not authentication infrastructure.

Follow-up to reviewed commit `28dfdd2f27bc2abfac90557fbdc08a8432be33aa`:
the model previously accepted offer floor100 → commit floor42 at high-water41.
The terminal now also compares against its pending offered floor. Regression
transcripts in `contracts/camera-enrollment-proposal/commit-floor-vectors.json`
cover below/equal/above floors, current and proof high-water, duplicate traffic,
corrected commits and the original timeout boundary. The existing wire revision
and message shapes stay the same: the max rule above was already normative.
Cross-message floor comparisons belong in the stateful model; JSON Schema alone
validates individual message shapes and numeric bounds.

Validation on 2026-10-24: 23 original enrollment checks and 22 new commit-floor
cases passed; removing the new offer-floor guard reproduces the review failure.
Full pytest: 838 passed, 7 skipped (dependency deprecations and an unawaited
AsyncMock warning remain). Ruff and Black passed for the two changed Python
files; schema comparison confirms only an explanatory comment was added.

Firmware/server owners must approve this revision and strict schema before runtime
work. Advertise both exact enrollment and CTL revisions only when implemented;
intersection-empty rejects the monotonic camera flow, not silently downgrades it.
Next: durable fenced owner + producer/readiness handlers + MB fresh-readiness flow,
then firmware implementation and real4623 acceptance. Released Windows53 and
IoT cooldown134 behavior remain independent and preserved.
