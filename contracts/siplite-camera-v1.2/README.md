# Camera observation / media-v3 adapter 1.2.0 proposal

Status: proposal for cross-stack review. No deployment, activation or hardware
acceptance follows from this packet. Camera RPC/config/local API remain
`siplite-camera/1.0.0`; this packet versions measured observations and the
camera-specific admission HTTP adapter. Frozen1.1 and enrollment0.2 are unchanged.

The exact selected HTTP bundle for camera inventory, prepare, enrollment,
readiness, lease, START, state, renew and STOP is all five headers:

- `X-L4-Media-Contract: l4-media/3.0.0`
- `X-L4-Camera-Contract: siplite-camera/1.2.0`
- `X-L4-Camera-Cadence: camera-cadence/0.1.0-proposed`
- `X-L4-Camera-Enrollment: camera-enrollment/0.3.0-proposed`
- `X-L4-Camera-Admission: camera-ctl-monotonic/0.2.0-proposed`

Missing, mixed and unknown combinations fail closed. Media HTTP receives only
its common media header and service authentication, not the camera headers.
The existing URL `/api/v2/media/*` does not change the envelope's version3.

Gauge84 `media_observations` contains camera_observation. Legacy camera1.0
actual_track may remain null. Never copy this observation into a legacy
projection as a version fallback. Its track references the exact frozen common
media3 track, not a camera-specific fork. The referenced schema SHA is in the
manifest. Resolve its URN locally; no network schema fetching is needed.

Capabilities advertise supported policy choices through the common
quality_options object. Both policies may use the same confirmed native track.
Profile selection is placed in the common descriptor before preparation and
is immutable for the attempt. Native size="", fps=0, bitrate=0 remain camera
configuration; they never enter the descriptor or get rewritten by observation.

Observation still requires validated original AU/GOP/SPS/profile/level, repeated
parameter sets and no B frames. Cadence0.1 policy bounds remain producer guards
(1..30fps; max20 above1920x1080, original timestamps); common schema parsing
bounds do not lift these policy limits. A fresh gauge is not enrollment,
readiness, command ACK, media RTP proof or browser decode proof.

Common descriptor contains only contract_version3, descriptor_revision,
source_type/source_id, geometry_generation, profile_id low/default and tracks.
Camera/cadence/enrollment/media authority markers remain outside it. Physical
MAC/port2, boot/path, issuer/floor and R/I lease semantics remain the separate
camera adapter. No desktop CTL2 or Windows capability binding is imported.

Run `python verify.py` with jsonschema installed. Examples are public synthetic
observations without credentials; they are not a hardware acceptance result.
