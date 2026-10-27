# IR-cut commissioning and configured-wiring diagnostics

Revision `siplite-ircut/1.0.0`. Device-only camera control; no STM32 operation.
The consumer/initiator is deliberately unassigned: no MenuBuilder or l4siplite UI
is part of this change. MQTT uses the existing main_app RPC transport.

## Methods and transaction

- RPC168 `CMD_IP_CAMERA_IRCUT_SEARCH`: inspect, start, status, cancel, apply, recover.
- RPC169 `CMD_IP_CAMERA_IRCUT_DIAGNOSTICS`: inspect, start, status, cancel, recover.

Every RPC completes with a correlated RES and gauge84/tag450 snapshot. No new
event type is allocated. Start202 means the device accepted an asynchronous
operation, not that wiring was found. Its final outcome is visible through status
RPC and the existing gauge. `session_id` identifies that operation independently
of each RPC's transport correlation UUID. Retries never extend its original
monotonic budget or replay a pulse/config POST.

Payload is `{ "dt": [item] }`; item always contains
`ircut_revision: "siplite-ircut/1.0.0"`, `action` and the exact `camera_mac`.
Optional `camera_id` is `cam:ip000001`. No credentials, URL, shell command,
register address or arbitrary GPIO write is accepted.

Inspect reads configuration, GPIO ownership/mux and capabilities, returning the
current device `boot_id`, an opaque `revision`, candidate counts and existing
IR-cut assignment. It does not drive outputs or change configuration.

Start requires `session_id` UUID, current `boot_id`, `expected_revision` from
inspect and `allow_disruptive: true`. `budget_ms` defaults to300000; it bounds
the device operation, separately from RPC delivery/response TTL. Optional `pairs`
is an ordered list of distinct GPIO pairs to test. Omitted pairs are generated
from the camera's eligible pins: configured pair first, adjacent/in-bank pairs,
then remaining pairs. Hints are not wiring assignments. GPIO10/11 is not a
universal default. Every pulse rechecks actual ownership/mux and camera identity.

RPC169 reads the configured pins afresh and tests only that assignment. It never
falls back to scanning other pins and never saves replacement wiring. A missing,
single-pin or unsupported driver is reported explicitly; inspection of such a
configuration is still useful and does not manufacture a two-pin assignment.

Status/cancel address the exact `session_id`; stale sessions cannot affect a new
operation. Apply is RPC168-only, requires the same completed session, current
`boot_id` and `expected_revision`, and persists only optically supported pin
assignments after explicit request and readback. It does not expand RPC161's
write allowlist. Provisioning remains a possible future caller, not an implicit
trigger. No automatic scan, apply or pulse occurs on boot.

## Execution and evidence

The existing camera worker serializes HTTP and advances the operation in steps,
so status/cancel do not wait for an entire scan. Active forwarding rejects
commissioning; the operation does not silently stop another viewer. Physical
port2/MAC/IP and current native/custom credentials are checked before access.

Use native GPIO pair drive immediately followed by park/float, not a held level
across optical capture or queued RPC processing. Electrical pulse duration and
native camera watchdog behaviour still require hardware verification; HTTP
acceptance alone does not establish them.
Unknown ownership, avoid/assigned pins, non-GPIO mux or an API refusal prevents a
pulse. A/B/A with repeated frames must show a repeatable optical transition above
the measured within-stage noise. Darkness, clipping, motion, insufficient colour
evidence and weak/nonreversible transitions are inconclusive, not valid wiring.
Report optical evidence separately from API/software state and user observation.

Capture headers determine NV12/NV21 geometry/strides. Stream the frame and retain
only a small luma/colour sample in PSRAM, never a full5MP frame in internal RAM.
Metrics include gmin, mex25, illumination, within-stage variation and reversible
delta; timestamp ordering is within this operation, not a device/server UTC match.

Temporarily hold exposure/gain/AWB and prevent automatic night/grayscale changes,
using only schema-supported native controls. A private recovery journal records
the original owned fields before mutation. Cleanup restores those fields and
releases coils on success, cancel or error. Recovery after interruption is an
explicit RPC, with the original camera identity; no automatic replay or scan
resume. Missing/uncertain physical position remains unknown. Never retry an
ambiguous pulse or persistent write as though it had failed before execution.

## Wire observation and rollout

Gauge450 gains an independent optional `ircut` observation with this revision,
boot/session/snapshot IDs, camera MAC, state, progress, configured/found wiring,
optical evidence and cleanup/recovery status. Existing frozen camera/media schemas
are not edited or used to claim this additional capability. No frame bytes or
credentials enter RES/gauge. General camera physical-writer admission still
applies; deployment/activation and any caller UI are separate coordinated steps.

Hardware facts used in design: current native camera returns NV21 at2592x1944,
7558272bytes; `/api/v1/gpio`, `/api/v1/pinmux`, `/api/v1/live` and schema are
available. Live null removal was checked on an already absent ISP field without
changing effective ISP configuration. These observations do not yet prove the
ESP32 implementation or wiring on a different camera.

Subsequent native tests: AWB `/live` is refused despite schema `x-live:true`;
successful `/config` has an empty HTTP200 body. Journaled config writes were
checked for AWB manual/null/auto and a temporary numeric exposure. A full
AE/AWB/gain hold retained identical hardware metrics across two samples, then
the exact original configuration and video0 were restored. Readback rounds
gain5.431640625 to5.43164; firmware compares within half the declared native
metric unit. These camera API checks are not ESP32 RPC or GPIO acceptance.

## Prepared admission

RPC168/169 are registered independently of the frozen camera/media revisions.
The strict payload validator rejects credentials, arbitrary fields, malformed
IDs and replacement pairs on diagnostics. Admission requires a fresh main_app
gauge advertising `ircut_revision` and `methods:[168,169]`. Physical start/apply
retain the existing camera writer gate and exact boot/revision checks. Cleanup
remains available for the matching camera/session after that gate is disabled.
No gate, UI or deployment is activated by this PR. Firmware is a separate PR;
host vectors and a successful build do not constitute hardware acceptance.
