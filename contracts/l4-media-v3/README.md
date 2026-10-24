# Unified L4 media 3.0.0 — implementation candidate, milestone 1

Owner: etranprocessing contract authority; integration coordinator owns this
package. Consumers must copy the exact manifest-pinned schema, not fork it.
Current candidate SHA is in manifest.json. Changes require a refreshed manifest
and notification in the shared task status before consumers finish deployment.

## Task intake

Goal: a useful native-resolution desktop stream on terminal 773, using existing
Medium/HD choices, and one reusable media contract for desktop and camera sources.
Producer: l4capture via l4desk; IoT owns control admission/state; MenuBuilder owns
the quality request and orchestration; l4media owns media routing/SDP. No database
migration is required. Camera firmware/admission remains with its parallel owner.
Tests and deployment are authorized. Camera hardware is not part of this milestone.

## Version boundary and scope

The common descriptor and producer/media capabilities carry `contract_version:3`.
Media start/identity/renew/stop/response envelopes also carry `contract_version:3`.
Existing CTL command/ACK/event `version:2` and native IPC version 2 remain unchanged:
these identify control/binary framing, not the negotiated media descriptor.
Do not introduce CTL3, IPC3, new MQTT clients or new lease verbs for this work.

Use `X-L4-Media-Contract: l4-media/3.0.0` on BFF-to-IoT/media HTTP requests selecting
this contract, including capabilities and state. Retain existing URL paths and
internal function names for this milestone. The existing UI inventory query
selects `contract_version=3`. Missing/unknown/mixed selection must be rejected
clearly on the v3 flow, not silently decoded as v2 or downgraded to H264.
Descriptor equality/canonical hashing includes its new version field.

We are converging development stacks, not running a legacy migration program.
Deployment interruptions are allowed. Do not build parallel fallback machinery
just to preserve interim versions. Frozen historical contract files stay intact;
do not claim old consumers can accept v3. Existing unrelated operations remain.

## Common stream, source-specific authority

Desktop, USB camera and IP camera use the SAME descriptor/track shape. Existing
source_type/source_id/geometry_generation, descriptor_revision and profile_id
remain. No camera-only width/height limits or desktop-only track variants.
Source-specific enrollment, boot/issuer fences, lease ownership and credentials
are outside this common media object; the camera owner retains those protections.
The `capabilities` definition here is the existing desktop probe/admission
projection with a version marker; cameras do not acquire Windows fingerprint
fields. The common formats/descriptor/options are reusable independently of that
desktop-specific evidence wrapper.

Descriptor tracks are concrete facts, never `auto`, zero dimensions or a guess
from an encoder setting. FPS is the declared nominal/target cadence, not a promise
of exact instantaneous or achieved FPS. Do not retimestamp a camera or round an
arbitrary measurement to satisfy it; the camera owner's measured-cadence policy
remains a separate admission concern. Actual delivery FPS is telemetry.

Schema bounds (positive even dimensions up to 16384, FPS 1..120) are parsing
guards, not supported-mode promises or quality presets. Producers and consumers
must admit concrete formats using their resource/codec limits. Native currently
has an 8,294,400-pixel resource guard; fail explicitly beyond supported resources,
never silently shrink. Supported codec subset remains H264 baseline/main/high,
HEVC Main 8-bit 4:2:0 Main Tier, no B-frame reordering, existing RTP packetization
and feedback. HEVC levels extend through 186; the actual SPS supplies the level.
Do not relabel profile/tier/level or relax bitstream verification.

## Medium and HD policies

Existing wire IDs remain `low` (Medium) and `default` (HD). `quality_options`
deliberately reuses profile_id; no third choice, subscription implementation or
new generic options framework is introduced. The profile requests a policy,
not a prescribed raster. The chosen concrete track is reported before START.

Both desktop profiles prefer the complete native frame and never upscale.
Even-alignment adjustments for 4:2:0 must be explicit in actual dimensions.
Initial desktop experiment: Medium targets 10 fps, 2 Mbps mean / 3 Mbps encoder
peak; HD targets 15 fps, 4 Mbps mean / 6 Mbps encoder peak. These are trial rate
budgets, NOT measured results or proportional pixel formulas. Coordinator may
tune budgets/cadence from 773 evidence without changing the schema or wire IDs.
Do not use the profile to impose a camera FPS/size preset. A camera may expose
one available format for both choices, or refuse an unsupported policy explicitly.

Priorities: readable text, stable static quality, bounded latency, then cadence.
Preserve the successful text-quality work from native PR8. Network budget means
observed traffic over an interval; do not mistake every keyframe burst for abuse
or infer bitrate from dimensions alone. Browser fit/native display scaling stays
unchanged and does not reduce transmitted traffic. No transcoding is added.

## Deployment and acceptance

Order: media agent deploys l4media -> IoT agent deploys app1 -> MenuBuilder agent
deploys backend/frontend -> coordinator installs changed native tools on 773 and
performs browser acceptance. Each agent publishes its exact deployed revision,
digest and header/version smoke result in its task result. Do not wait for a
production idle window or prepare separate rollback steps; owner requested
forward progress and accepts interruption. Do not touch infrastructure services.

Offline validation is per changed stack. Live acceptance only on 773: small-frame
fixtures plus real 1920x1080 and 3000x2000 displays, native geometry, both profiles,
static PowerShell/gray text, scrolling, motion recovery, measured traffic/cost,
fresh decoded frames and sustained quality. STOP investigation is deferred.
Only after server + desktop acceptance does the coordinator publish the final
contract/hand-off to the camera firmware agent. No camera runtime changes or
camera acceptance claims now.
