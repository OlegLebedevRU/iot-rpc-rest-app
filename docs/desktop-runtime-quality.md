# Desktop quality channel (optional)

The original START publisher is the only runtime quality writer. The optional
`X-Video-Quality-Writer` UUID header is bound once during initial desktop START;
only its SHA-256 digest is stored alongside the immutable original tenant/user/
login-session identity. Duplicate START does not replace it. The key is never
included in CTL/media envelopes or returned by state/observer APIs. Tabs sharing
one login therefore cannot acquire another tab's quality channel by joining.

GET `devices/{sn}/video-quality?stream_instance_id=...` under the internal remote
input router performs normal tenant/device access and returns measurements only.
POST `lease/{lease_id}/video-quality` accepts stream UUID, writer UUID key and
target kbit/s. It checks the active original publisher lease and exact original
identity in the Redis video transaction, with no superuser override. Legacy
STARTs without this extension keep ordinary streaming; no START gate is added.

Accepted intent reserves a generation and sends CTLv1 `stream_quality_set` on
the existing `srv/{SN}/ctl` connection, QoS1/no retain. Fields: SN, command UUID,
lease UUID, stream UUID, generation, target_bitrate_kbps, issued_at_ms and
expires_at_ms. Five-second expiry is clipped to the active lease. The writer key
does not leave the server. The requested target cannot exceed the selected low
(2000) or default (4000) profile ceiling.

The agent's ordinary ACK means accepted, not encoder application. Native
`stream_quality_report` on `dev/{SN}/ctl`, QoS1/no retain, supplies exact lease/
stream/agent boot, increasing sample sequence, applied command generation,
applied_kbps, status, transport_age_ms, delivery_kbps, flags and raw_replaced.
Flags:1 optional actuator path available,2 measured transport pressure,4 fresh
local transport measurement. Different epochs/boots, replayed samples and future
generations are rejected. Other observer feedback cannot issue rate changes.

A driver refusal remains explicit and does not stop ordinary video. An expired
or unpublished command remains unconfirmed, not falsely applied or permanently
classified as an unsupported driver. A fresh source report remains authoritative
for the current rate and permits the initiator to retry with a new generation.
Delivery throughput is not channel capacity; raw replacement is not RTP loss.

Validation:16 focused ownership/epoch/generation/application/HTTP/MQTT cases,
plus the existing170 video-control cases passed. New runtime module, modified
video control/bridge and new tests have zero Pyright errors; Black's API safety
check passes. Pre-existing lint/type diagnostics in the large HTTP router occur
outside changed sections and were left unchanged under the owner's scoped-check
instruction. No broker configuration, schema migration or camera contract change.
Coordinated deployment and browser/native constrained-link acceptance remain.

Follow-up from live selection: an initial DISPLAY1 capability probe can overlap
START for DISPLAY2. Media3 desktop requests now await the current probe and then
measure the selected display, within the original request deadline and remaining
MQTT TTL. They do not cancel another query, accept its source as their own, or
restart probing after invalidation. Legacy negotiation behavior is unchanged.
Two regression cases plus the existing capability/runtime/video cases pass:
194 total. Ruff's existing B905 diagnostic at video_control.py's untouched zip
is excluded from the scoped check; changed code, Pyright and Black AST safety pass.

## Coded raster extension (candidate, not yet deployed)

The same CTLv1 command optionally carries `raster_step`. Its source must first
report `quality_version:2` with all of `coded_width`, `coded_height`, `raster_step`,
`ceiling_kbps` and `last_idr_bytes`. Original writer/tenant/user/session/lease/epoch
checks are unchanged. An old command omits the new field; legacy agents do not
need runtime quality support to start or continue H264.

Every tier halves the initial coded dimensions and rounds only to even4:2:0.
app1 validates this geometry against the immutable START track and rejects a
reported ceiling above the selected profile. A lower source ceiling is respected.
Initial START/READY snapshots are not rewritten. Pending geometry is confirmed
only by a source report after its first new IDR has been sent, not by an ACK.
This source-side confirmation does not imply that a browser has cleared backlog.

Modern desktop H264 discovery can proceed with the HEVC chain flag disabled when
an independently measured H264 capability exists. Its START still requires the
same fresh exact capability and normal ownership/lease checks; HEVC admission
retains its own chain gate. No camera or frozen media schema is changed.

Current scoped validation:20 quality cases include raster opt-in, complete reports,
pending/application, immutable START, effective ceiling and modern software H264
START without the HEVC chain. The combined video/quality suite previously passed190
cases. Coordinated native/browser acceptance of this extension remains pending.
