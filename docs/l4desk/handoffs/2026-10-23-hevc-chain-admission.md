# HEVC chain gate: admission before concrete codec commit

Baseline: accepted master `8fee17436c9d7f064011b61a676eb86fa5340eb8`.
Producer/owner: IoT video capability HTTP projection. Consumer: existing BFF
availability/Auto decision. Frozen `hevc-contract/2.0.0`, digest
`f065b967cd10c2c709fb394ef9e6c2ecf74f77de060d88c9a821cc9069766ac4`, unchanged.

With the hardware capability ready and the IoT HEVC-chain gate off, the old
inventory projection still negotiated v2. BFF selected an HEVC descriptor for
Auto; IoT correctly refused that concrete command with codec_mismatch before
encoder dispatch. Auto could not use the still-available legacy H.264 path.

The inventory projection now closes new negotiation while the hardware HEVC
chain is disabled. BFF uses its existing unavailable branch and prepares concrete
legacy H.264 before START. No retry of an attempted/failed HEVC producer is added.
The measured hardware capability and running v2 record/lease are not invalidated;
existing readers, events, renew and STOP remain unchanged. The explicitly
allowlisted test-camera exception is retained only for a test-prefixed camera
source/backend; allowlisting a desktop alone does not reopen hardware admission.
No new HTTP keys, wire enums, MQTT topics, migration, dependency or flag default.

Six regression cases cover cached/refresh admission, running-epoch preservation,
and the camera exception including unlisted camera and allowlisted desktop.
The first three fail on baseline. Windows Python3.14: 758 passed, 7 skipped;
94 video-v2 cases passed before adding the three camera-boundary cases.
Focused ruff check/format and Black pass. Additional pyright over both touched
files reports the same18 diagnostics as a clean baseline with the same environment;
no diagnostic is added and pyright is not reported as green. Frozen G0 passes.
Two pre-existing nested conditional expressions were normalized without changing
codec selection or HTTP status mapping, so both formatters agree.

TASK-60 owns the independent deployment receipt, exact image/source hashes and
post-deployment checks: with the chain gate off, explicit HEVC must be refused,
Auto must decode H.264 and an existing H.264 publisher must keep its epoch/PID.
Do not infer deployment, hardware admission, signing or release from this document.
The native cold-start budget and Windows elevated SCM gate remain separate.

The read-only source scan found an unchanged excluded example private-key file.
It was not inspected further or included in the changed release inputs; no real
credential value was printed. Deployment still requires the standard image-layer
secret scan. Credential investigation/rotation in excluded examples is separate
from this admission change.
