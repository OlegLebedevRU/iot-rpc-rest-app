# Camera observation / media-v3 adapter 1.3.0 proposal

Status: owner proposal only. This packet does not implement runtime, advertise
negotiation support, authorize deployment or establish hardware acceptance.
Camera RPC/config/local API remain `siplite-camera/1.0.0`.

The observation/capabilities shape is identical to frozen1.2. Only versioned
identity, title and selected camera/cadence/enrollment constants change. Frozen
1.2, common media3 and CTLv1 admission0.2 bytes are unchanged. The common track
and quality_options are external references, never copied or forked here.

Exact selected camera HTTP bundle:

- `X-L4-Media-Contract: l4-media/3.0.0`
- `X-L4-Camera-Contract: siplite-camera/1.3.0`
- `X-L4-Camera-Cadence: camera-cadence/0.2.0-proposed`
- `X-L4-Camera-Enrollment: camera-enrollment/0.4.0-proposed`
- `X-L4-Camera-Admission: camera-ctl-monotonic/0.2.0-proposed`

All five markers select one bundle; missing/mixed/unknown revisions fail closed.
BFF to MEDIA sends only its common media header and service authentication.
Camera authority markers remain outside the common descriptor. Old offers and
old descriptor authority cannot silently acquire the new cadence interpretation.
Boot/issuer/floor counters, physical binding, R/I/readiness and lease deadlines
are retained; changing selection requires fresh full enrollment/readiness.

Canonical cadence0.2 owner packet lives in IoT `contracts/camera-cadence-v0.2/`;
enrollment0.4 in `contracts/camera-enrollment-v0.4/`. Initial owner source is
91ca28a9200ba8a989611e5b21b8e15d57617283. This observation schema describes the
representation only; it does not substitute for the producer's executable
full AU/GOP/PS/no-B proof or cadence policy. Markers, ACK, RTP arrival and browser
decode do not individually prove those facts.

Cadence0.2 chooses a unique nominal integer FPS from1..120 using validated
original RTP intervals and every overlapping four-second window. This replaces
cadence0.1's original-anchor phase policy only under the new explicit revision.
No desktop20/30FPS geometry budgets apply. Actual terminal resource/profile
limits remain independent; schema acceptance does not promise120FPS capability.
No actual rational measurement, SDP/config hint or rounded mean is inserted into
track.fps. Native Auto size="", fps=0 and bitrate=0 remain unchanged camera
configuration. Original RTP timestamps are never rewritten to satisfy proof.

At the first eligible complete GOP boundary, the canonical policy freezes the
unique nominal FPS and maximum completed acquisition GOP span G0. Common
keyframe_interval_ms is ceil(G0/90), a nominal acquisition reference. It is not
an instantaneous measurement, exact repeated duration or guaranteed maximum.
The external policy permits earlier fully validated IDR+parameter-set entry
points, while independently bounding later growth to105% and five seconds.
All complete-AU, repeated-PS, no-B, source/path/codec/geometry and continuous
revocation requirements remain mandatory. See the cadence owner document for
checked arithmetic, original10s deadlines and bounded history rules.

Gauge84 `media_observations` carries the camera_observation. Legacy camera1.0
actual_track may stay null; do not project this as a legacy version fallback.
Medium/HD mean low/default policy choices; the same confirmed native format may
serve both. Policy selection changes the immutable descriptor before START,
never camera configuration. No optional telemetry or new hint fields are added.

`manifest.json` pins exact raw bytes, including the frozen common schema hash.
Resolve the common URN locally; no network schema retrieval is needed. Run
`python verify.py` with jsonschema installed. Public synthetic examples and
schema vectors are offline representation checks, not producer/live acceptance.
