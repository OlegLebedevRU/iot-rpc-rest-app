# Desktop session lifecycle55 handoff

IoT STOP closes server session authority; publication is not producer-exit proof.
The existing `confirmation=null` for non-running states remains; no new wire field.
Synthetic producer_lost errors now set current_stream_terminated=false because
the server has no physical exit evidence. Native errors preserve their reported
boolean. Consumers must not infer resource release from logical stopped alone.
MB stops booking that final interval as confirmed; native blocks new START until
owned resource cleanup is confirmed. No automatic replay of the old session.

H.265 applicability is invalidated only for concrete codec/encoder/source/format
failures, not lease_invalid, caller_cancelled, start_timeout, producer_lost or
network_failure. Persistent hardware facts remain on the device. This does not
turn every failed START into available runtime media.

The camera boot/issuer companion is a review-only proposal in
[camera-boot-issuer-enrollment.md](camera-boot-issuer-enrollment.md), based on
reviewed PR136. No camera runtime/writer/allowlist change is deployed by it.

Verification: focused desktop video tests and offline contract vectors; combined
browser acceptance on773 follows MB, app1 and changed native deployment.
