# Camera adaptive quality: candidate 0.1

Status: **proposal and offline preparation**, not a negotiated runtime revision.
User authorized preparation without deployment or browser START on 2026-10-27.

Canonical candidate: `contracts/runtime-quality-proposal/schema.json`.
This extends quality control; it does not replace or fork `l4-media/3.0.0`.
Existing desktop quality v1/v2, camera enrollment0.5, admission0.2 and camera1.4
remain byte-for-byte unchanged. The candidate is not accepted by their handlers.

## Reuse and ownership

Use the existing original-initiator proof: `X-Video-Quality-Writer` at START,
SHA256 digest in the original publisher record, same tenant/user/login session,
lease and stream. Other observers may read actual quality; they never replace
the writer, including a superuser or another tab of the same login. The writer
credential stays on the HTTP side and is not present in a firmware command.

| Producer → consumer | Existing transport | Candidate | Delivery / confirmation |
| --- | --- | --- | --- |
| Initiator → BFF → IoT | POST stream/quality → lease/video-quality | QualityRequest, explicit quality_revision | Accepted intent is not application |
| IoT → main_app | srv/SN/ctl | CameraQualitySet | QoS1, no retain; command_id correlation |
| main_app → IoT | dev/SN/ctl | CameraQualityReport | QoS1, no retain; ordered sample_seq |
| IoT → all observers | Existing quality GET | Requested, actual, generation/status | Reading does not grant write ownership |

No new RPC method/event/topic, STM32 work or second MQTT client is introduced.
Existing main_app presence and RPC RES+gauge84 are preserved.

## Fields and semantics

`quality_revision=l4-quality/0.1.0-proposed` is required explicitly. Omitted
revision is not inferred from a camera mode or a successful old START.
`target` is partial: omitted axes preserve their last requested settings.
The initiator target and actual encoder state remain separate.

| Field | Units / interpretation | Current actuator evidence |
| --- | --- | --- |
| target_bitrate_kbps | Encoder target, 0 native Auto | Local config POST/readback works, persists config |
| size | Native coded raster WxH, empty native Auto | 5MP/3MP/2MP locally confirmed, encoder rebuild |
| target_fps | Frames/s, 0 native Auto; fractional expressible | This camera API accepts integer FPS only |
| preset_id | Source-resolved defaults; explicit axes override | Names are conveniences, never a mode whitelist |
| codec_policy | auto/h264/h265 preference | Runtime codec switch not implemented by this stage |
| rate_control | Source-declared mode | Validate against actual camera schema |
| gop_seconds | Positive GOP interval in seconds | Maps to native string gopSize; validate source schema |

No desktop100..4000 limit, HD/Medium ceiling, fixed FPS, halving-only raster rule
or closed MP list is introduced. Exact JSON integers use the interoperable
0..2^53−1 representation; this is not a quality budget. Source-specific schema,
measured resource and negotiated decoder constraints remain factual checks.
Capability advertisement must identify implemented axes and persistent effects.
Being expressible in this candidate does not mean an actuator implements it.

Reports reuse generation and sample_seq. A source may temporarily reduce bitrate
under measured queue pressure and recover toward the latest initiator target.
Both directions keep the accepted generation and increment sample_seq; origins
are initiator/source_pressure/source_recovery. No source-side ownership takeover,
new lease or generation per autonomous rate step is needed. Pending/unconfirmed
must not invent actual settings, measured traffic, or successful decoded frames.

## Camera authority and time

The adapter carries existing lease_id, stream_instance_id, boot_id, issuer_epoch
and admission_seq from the active START; quality generation orders the targets.
Do not substitute desktop UTC admission for the camera's enrolled R/I mapping.
Issuer deadline = issued coordinate + min(remaining active lease, command budget).
Retransmission reuses original bytes/ID/deadline. Delivery time never grants a new
TTL. STOP/retire/issuer takeover invalidates pending quality work for that attempt.
The original writer must be rechecked by the server before execution/publication.
Source identity and exact physical camera remain fixed; raster is mutable state.

The schema validates structure. `quality_contract.py` additionally rejects empty
targets, nonpositive command lifetimes, incomplete actual rasters and a confirmed
status without actual. Runtime replay/lease/identity checks are still the control
adapter's responsibility; these models do not establish authority on their own.

## MEDIA boundary and actual descriptor

START descriptor is immutable history; current coded raster/FPS are actual facts.
The existing common media descriptor must be reused when reporting a full actual
descriptor. No copy with relaxed validation is added here. Its integration and
the camera immutable binding extension still require an explicit negotiated
revision; do not simply disable existing descriptor-hash checks.

Janus route creation pins codec/PT/rtpmap/fmtp/ports, MID/media layout and media
options. These are private MEDIA binding, never quality PATCH fields. Do not
derive replacement fmtp from a changing SPS and silently edit/recreate the route.
Current scope excludes codec switching, mountpoint reconstruction and reconnect
of all observers. Local camera resize changes SPS level; continuous compatibility
with the existing Janus offer and Chrome must be verified separately.

## Implementation boundary and rollout

Prepared: candidate typed payloads/schema, native field projection and fixed
deadline arithmetic with offline vectors. No handler, capability advertisement,
automatic quality loop, new writer, source actuator or live descriptor update is
enabled by this patch. `/api/v1/live` refused native bitrate in the hardware probe;
config POST is persistent. Do not publish a periodic config writer as a transient
queue-control actuator without addressing write persistence/rate and recovery.

Next: agree exact camera extension revisions; implement fenced camera quality
commands and reports, bounded actuator with explicit persistence policy and
down/up behavior, then BFF/UI reuse of the original initiating writer. Preserve
desktop v1/v2 compatibility. MEDIA changes only if live raster requires them.
Owners review and deploy their changed stacks after coordination; current task
does not deploy, activate gates, install another firmware or start browser video.
Offline models/vectors are not runtime or hardware acceptance.
