# Camera media/observation 1.1 implementation candidate

This additive package is owned by etranprocessing. It does not alter frozen
camera1.0, HEVC2.0, local camera control/credentials or enrollment0.1 artifacts.
Deployment and runtime gates remain off. It is metadata validation, not proof of
original-RTP decoding, enrollment, readiness or a producer lease.

Select all four headers together:

```
X-L4-Camera-Contract: siplite-camera/1.1.0
X-L4-Camera-Cadence: camera-cadence/0.1.0-proposed
X-L4-Camera-Enrollment: camera-enrollment/0.2.0-proposed
X-L4-Camera-Admission: camera-ctl-monotonic/0.2.0-proposed
```

`hevc.schema.json` is standalone. Select definitions explicitly through `$defs`:
`camera_descriptor`, `camera_observation`, `camera_capabilities` and existing
media request/response definitions. `camera_track` retains frozen camera track
limits. The 1.1 descriptor branch accepts only camera1.1, requires cadence and
preserves immutable equality across media operations. Neither marker is optional.

`camera_observation` contains exactly `camera_contract_revision`,
`cadence_revision`, `source_id`, `geometry_generation`, `actual_track`, and
`capabilities`. Device geometry generation is a nonnegative bounded integer,
incremented upon source format/policy/evidence-epoch invalidation. Copy it exactly;
do not derive it from discovery generation. Actual track must come from validated
original-RTP AU/GOP/PS evidence under the explicitly selected cadence policy.

`camera_capabilities` contains four required arrays: `camera_contract_revisions`,
`camera_cadence_revisions`, `camera_enrollment_revisions`,
`camera_admission_revisions`. This strict candidate describes this exact bundle;
unknown or mixed revisions fail. The selected media capabilities response includes
the same four lists and the existing runtime-verified format matrix.

## IoT HTTP integration shape

For an explicitly selected1.1 `video-capabilities` request, retain the existing
tenant/SN-authorized outer view and fresh main_app/gauge checks. Add
`camera_observation` validated by the definition above and `camera_capabilities`
validated by its definition for IoT's own selected support. The observation's
capabilities represent device support, not inferred server support. The existing
`camera` member supplies source identity, discovery/physical port/MAC/auth facts.
The selected projection's outer `camera_contract_revision` is1.1; local camera
RPC/gauge control schema remains1.0. BFF verifies observation source against the
camera member and independently validates all three peers' capability lists.
Do not project1.1 measured cadence as a legacy1.0 constant-track fact.

Prepare still sends exactly descriptor and physical_camera_mac. IoT checks the
descriptor tracks and geometry against its fresh trusted1.1 observation and
prepares `port2/<discovery.generation>/<observation.geometry_generation>`.
Enrollment0.2 full-offer schema/messages remain owned by IoT. Include this exact
descriptor, full binding and their canonical digests; do not echo an opaque hash.

`canonical-vectors.json` provides ASCII/integer-domain RFC8785 canonical descriptor
and complete binding bytes/digests for cross-language tests. Both markers enter
the descriptor digest. A different cadence policy with identical track facts
must produce a different digest and fail selected-schema validation.

Pin `manifest.json` schema SHA before integrating. Run `verify.py` for schema,
canonical vector and frozen-baseline checks. No runtime compatibility claim follows
from schema tests; real4623 firmware/media acceptance remains separate.
