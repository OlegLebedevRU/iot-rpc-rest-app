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
