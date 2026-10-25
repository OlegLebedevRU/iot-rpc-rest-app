# Camera observation / media-v3 adapter 1.4.0 proposal

Owner packet only: no runtime advertisement, deployment or hardware acceptance
is authorized by this packet. Camera RPC/config/local remain1.0.0.

The observation and capabilities shape is identical to frozen1.3. Only identity,
title and exact camera/cadence/enrollment constants change. Common media3 track
and quality options remain external references. Frozen1.3 and older packets,
common media3 and CTLv1 admission0.2 bytes are retained unchanged.

Exact camera HTTP selection (all five required, mixed selections fail closed):

- X-L4-Media-Contract: l4-media/3.0.0
- X-L4-Camera-Contract: siplite-camera/1.4.0
- X-L4-Camera-Cadence: camera-cadence/0.3.0-proposed
- X-L4-Camera-Enrollment: camera-enrollment/0.5.0-proposed
- X-L4-Camera-Admission: camera-ctl-monotonic/0.2.0-proposed

BFF to MEDIA sends only the common media header and service authentication.
Camera authority revisions remain outside the common descriptor. Revision
changes require fresh full enrollment/readiness, never reinterpret old offers.
Boot/issuer/floor, physical binding, R/I and lease deadlines remain unchanged.

Normative cadence0.3 and enrollment0.5 are owned by IoT in their corresponding
versioned packets. Cadence0.3 obtains declared nominal FPS from the authenticated,
selected video media section of the actual camera SDP (`a=framerate`, exact
integer1..120). The parser/source adapter must bind the metadata to that selected
track and camera session; unrelated media sections, ambiguous/invalid values,
configuration Auto sentinel and arbitrary rounded achieved means are not nominal
authority. Real source evidence for the current camera declares framerate20.
This is a declared target, not an achieved-rate ceiling. Common track.fps carries
that nominal integer; actual delivered FPS is telemetry and cannot kill a valid
stream merely for differing from the target.

There are no2% tolerances,4s/32s rate windows, inferred unique-F candidates,
constant-rate lattice or105% GOP growth requirement in this new policy. READY
requires one complete validated GOP with two verified IDR+parameter-set boundaries,
real SPS/profile/level/geometry, full AU, no B frames and supported packetization.
Observed nominal GOP is represented within250..5000ms; that scalar is not an
instantaneous equality or constant-runtime-GOP promise. A bounded30s IO acquisition
budget supports discovery and a5s GOP and is not an FPS gate or a new lease budget.
Full bitstream/PS/codec/geometry/physical-port2 authority and lease safeguards stay
mandatory; source/authority changes retire the attempt. Owner vectors define the
exact missing/invalid metadata and GOP observation behavior.

Native Auto size="", fps=0 and bitrate=0 remain camera configuration. RTP
timestamps and camera settings must not be rewritten to pass admission. No
desktop20/30FPS geometry budgets are camera limits. No telemetry/hint fields are
added. Medium/HD remain low/default policy choices; both may use one confirmed
native format. ACK, fresh RTP and browser decode are separate proofs.

Gauge84 media_observations carries this object; legacy camera1.0 actual_track
may remain null. manifest.json pins raw schema/example bytes and common3 SHA.
`python verify.py` performs offline representation/negative-vector checks only.
