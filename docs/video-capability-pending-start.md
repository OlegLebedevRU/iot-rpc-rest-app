# Concurrent desktop capability requests

## Incident and scope

On 2026-10-26 terminal773 was rejected with `negotiation_unavailable` before
native capture started. Production revision6aafd0e is also the current
origin/master base for branch `fix/video-capability-pending-start`.

Observed UTC timeline:

-17:05:37.658: agent receives inventory query for the secondary display.
-17:05:39.467: concurrent START capability request returns HTTP200 with no
 negotiated capability; MenuBuilder rejects START with422 and releases its lease.
-17:05:42.146: agent publishes correlated ready capability; the first inventory
 request completes at17:05:42.538.

The `VideoControl.capability` transaction correctly prevents duplicate queries,
but a caller finding another pending query returns the current empty snapshot.
This turns an in-progress cold probe into an apparent unsupported negotiation.
Native capture timing/NV12 changes do not execute on this refusal path.

## Change and invariants

App1 owns the query, correlation and deadline. Concurrent inventory and START
requests for the same source/profile/media selection/server epoch now share the
existing bounded wait. Only the original publisher sends and retires its query.
A cancelled waiter cannot clear another request's query. Transaction retries
discard any prior join candidate. Waiting uses the earlier of the existing
query expiry and the caller's normal budget; no TTL is extended.

Source/profile mismatch, invalidation, expiry, nonce, binding and final fresh
capability checks remain. No wire schema, MQTT client, topic, QoS/retain policy,
lease, camera admission, fallback or native binary is changed. Redis casts only
describe the existing decode_responses=True connection; no runtime checks added.

## Validation and deployment boundary

Regression tests cover delayed correlated ACK versus an unrelated nonce, no
second publication, cancellation ownership, source/profile isolation, original
expiry and invalidation. Existing media-v2/v3, legacy, HTTP and cold-start tests
are included in the focused test run. No broker/database/production test access.

Production was not changed or restarted. A normal warm retry succeeded in the
existing visible Chrome: START200, actual H2651920x1080,100fresh playback frames
over10seconds,1video playback dropped frame. That stream was left visible and
its existing browser coordinator retains normal renewal/STOP ownership. This
is recovery evidence, not deployed-fix acceptance.

Final local checks:176focused tests pass. On unmodified production-base controller
the new regression module has4failures and2passes; with the patch all6pass.
Ruff check/format and Black check pass for all3changed Python files. Pyright
passes for the changed runtime controller and new regression module with app1's
module path. An additional check of the pre-existing large test_video_v2 module
reports14type errors outside the changed test; those unrelated tests were not
rewritten. The Redis boundary casts resolve its existing broad Redis return
annotations without changing runtime values. Diff whitespace and secret scans
pass. No unrelated utility rebuild, signing, release or server deployment.

The final browser recheck still shows active1920pixel-wide video, enabled STOP
and input controls, and no refusal alert, beyond the ordinary lease TTL.

Next release must use the normal app1 builder/registry/digest workflow after
review and coordination of any active streams. Post-deploy gate: overlap cold
inventory and START on each display, require one query and fresh decoded frames,
then ordinary STOP/release. Do not use warm retry success as this race's gate.
