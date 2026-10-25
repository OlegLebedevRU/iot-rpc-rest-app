# Camera media-v3 lease adapter candidate

This new camera-only HTTP metadata is outside frozen l4-media/3.0.0. It is not
an accepted production contract. Select the complete five-header camera1.2 bundle.
The DTO retains owner_user_id, owner_session_id, SN, stream scope and active state.
Only authenticated camera lease export may initialize the trusted Redis anchor.

`media_lease_expires_at` is floor-rounded integer seconds in one attempt UTC
coordinate, anchored to current issuer UTC once at initial export. Subsequent
exports advance only by issuer monotonic time and Redis PTTL. `expires_at` remains
legacy display metadata and MUST NOT authorize camera3. `media_remaining_ms` is
positive, at most 60000, bounded by both original monotonic anchor and live Redis
PTTL after read latency. The caller subtracts its entire HTTP round-trip before
using the budget. `media_clock_id` is a UUID4 retained immutably in camera state.
Renew requires the same stored clock ID. No camera fields enter common descriptor.

Real owner/session-scoped heartbeat may extend the active Redis lease and its
existing monotonic anchor. Reading, duplicates, old commands and polling cannot.
A delayed initial START remains capped by the expiry sent to MEDIA prepare even
if a later heartbeat extends the lease. Equality with expiry is expired. Missing,
corrupt, revoked, replaced, regressed or different-kernel anchors fail closed;
an active stream never initializes a replacement. Owner/SN/session/scope/active
key and stream identity checks remain mandatory. Generic desktop UTC semantics
and GenericLeaseRegistry.touch are unchanged.

MEDIA first START consumes the remaining original absolute expiry. Active MEDIA
renew maps the delta of exported absolute expiry onto its original monotonic
deadline; neither a UTC jump nor duplicate expiry grants another full TTL.
clock-vectors.json provides positive/negative UTC jumps, duplicate renewal and
delayed START examples shared with the MEDIA/BFF owners. Offline vectors and
mock Redis tests are not hardware or production acceptance.
