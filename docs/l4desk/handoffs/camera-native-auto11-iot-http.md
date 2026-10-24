# IoT Native Auto1.1 HTTP integration handoff

Status: implemented IoT continuation,2026-10-24, based on IoT141:5f4129a279b25cd49b5fe6c54d80477975940885. Gates stay off. The external publication handoff records the final IoT commit/PR.

## Negotiated capability/observation reader

Retain GET /api/internal/v1/remote-input/devices/{sn}/video-capabilities.
The1.1 branch requires all four exact headers:

- X-L4-Camera-Contract: siplite-camera/1.1.0
- X-L4-Camera-Cadence: camera-cadence/0.1.0-proposed
- X-L4-Camera-Enrollment: camera-enrollment/0.2.0-proposed
- X-L4-Camera-Admission: camera-ctl-monotonic/0.2.0-proposed

Response: keep the tenant/SN-authorized outer view with camera_contract_revision=1.1, negotiated_v2=false, video_capabilities=null, main_app_online, fresh and producer_adapter. Adopt the owner's pinned README shape: add camera_observation and camera_capabilities. camera remains the existing physical/control snapshot (discovery/MAC/auth), not a Native Auto track projection.

camera_observation is exactly the owner's strict camera_observation definition, including source_id, actual_track, device geometry_generation, cadence_revision and device capabilities. camera_capabilities is exactly the owner's strict camera_capabilities definition for IoT support: camera_contract_revisions, camera_cadence_revisions, camera_enrollment_revisions, camera_admission_revisions.

Gauge84/tag450 carries strict1.1 facts in a separate media_observations array, preserving existing control snapshots. No old projection or inferred generation is used for1.1. BFF verifies observation.source_id == camera.camera_id. Observation and capability lists grant no enrollment/readiness/lease.

Pinned media schema SHA256: bfd71ec96cf8de81657fd319c603f91a4769209887e32297fff4193752e3c62e.

## Prepare and enrollment

Keep POST /devices/{sn}/camera/admission/prepare with descriptor and physical_camera_mac under the selected full header bundle. The descriptor is validated against the exact owner1.1 package and observation, including device geometry_generation and policy. GET /devices/{sn}/camera/admission and POST .../readiness use the same selected revisions. Existing camera stream START uses the bundle plus X-L4-Camera-Readiness, preserving its media body.

New enrollment0.2 offer includes camera_contract_revision, cadence_revision for the1.1 branch, full descriptor, full binding, binding_hash, challenge, generation, epoch and floor. Proof/commit echo all accepted content; commit may raise floor. The firmware can compute descriptor_sha256 and binding_hash from the received complete offer after validating actual attachment and track facts, including server-chosen descriptor_revision. No opaque hash echo is sufficient.

IoT owns enrollment0.2 schemas/vectors in contracts/camera-enrollment-v0.2/. Enrollment schema SHA256: f1697a9506117b215d2d66fd63fd375e2ca23d7365bee5d10d2a6955f9c4e91b. The byte-identical media/observation package in contracts/siplite-camera-v1.1/ is pinned to MenuBuilder PR111 commit60a2bffc961dfc31caeea96a76bfb856484212b5. Its strict definitions are camera_descriptor, camera_observation and camera_capabilities. Every owner file hash is recorded in contracts/siplite-camera-v1.1.lock.json. Existing frozen packages and durable migration0013 stay untouched.

User scope clarification: implement only the new full1.1/enrollment0.2 bundle; do not add a constant1.0 variant of the new enrollment. Preserve existing immutable artifacts and accumulated authority counters.

## Persistent state and rollout

Authority JSON version2 validates the complete stored fence before and after each transaction. Complete version1 records are upgraded by changing only their version marker; boot, retired boots, issuer generation, counters and caches survive. Missing or malformed records fail closed. The immutable0013 migration still seeds version1. Rejected writes roll back instead of constructing defaults.

New camera.native_auto_enabled and existing camera.monotonic_runtime_enabled default to false. Existing writer/SN guards remain required. Offline schema/C checks and isolated PostgreSQL176 tests do not replace firmware4623 and real decoded-video acceptance. No production deployment or gate enablement is included.

## Validation on2026-10-24

Full pytest with isolated PostgreSQL176 enabled: **921 passed,7 skipped**, with5 existing dependency/AsyncMock warnings. The38 additional cases cover strict owner package pins, separate observations, all four required headers, full firmware-computable offer/proof/commit, rehashed binding/policy substitutions, byte/depth bounds, preserved/corrupt authority, floor100→42 rejection, original deadlines, takeover,70 renewals/cache bounds, media lifecycle and actual controller START/ACK/STOP through the persistent Redis reader.

All20 changed/new Python files pass Ruff and Black. Full repository Ruff still reports14 diagnostics in unchanged frozen/auxiliary files; none are introduced by this continuation. Both standalone package verifiers pass. Actual C canonicalization built with -Werror and SDK MbedTLS SHA256 matches descriptor, binding and full offer/proof/commit bytes/digests, including the4096/4097-byte boundary; report: contracts/camera-enrollment-v0.2/c-canonical-report.json.

The real PostgreSQL checks cover version1→2 preservation of floor100 and retired boot,8 concurrent increments, rollback of malformed state, immutable0013 migration/trigger and issuer takeover with stale-owner egress rejection. They use only disposable UUID schemas in a temporary PostgreSQL18 container on authorized176. Existing production infrastructure is unchanged. Frozen1.0/HEVC2.0/enrollment0.1/admission0.2, migration0013 and uv.lock have no diff.
