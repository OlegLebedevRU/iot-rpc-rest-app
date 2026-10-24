# HEVC admission invalidation: clear the previous read cooldown

Follow-up to IoT PR133 / hevc-monotonic/1.0. Resetting an admission snapshot
removed capability/pending but left next_probe_ms from the earlier query. A
read for the same selected profile then returned negotiated_v2=false for up to
30seconds without asking the agent, despite its retained hardware proof.

Clear that previous cooldown together with explicit transport/presence admission
invalidation. Keep the cooldown for ordinary failed probes and retain all nonce,
source, server epoch, geometry and START authorization checks. A new ACK is
required; no invalidated capability is promoted to READY or used for START.

Two regression cases (transport and presence change) failed on accepted PR133
and pass with this patch. Focused video/camera tests:171 passed.

No wire field/schema, lease/TTL/START semantic, camera CTLv1, firmware writer or
allowlist changes. The firmware coordination source remains
contracts/hevc-monotonic-v1 and docs/hevc-monotonic-time-firmware-handoff.md.
The existing Windows candidate1.13.53, MB frontend/backend and signed EXEs stay
unchanged. Deploy only the IoT app1 image built from the accepted commit.

Live53 checks proved actual H.265 on both displays at Medium, secondary HD,
fresh applicability while encoding and persistent hardware proof after a new
agent boot. During further acceptance an independent capture-child stop did
not confirm cleanup; the next primary HD START was correctly refused as a
conflict. That is not evidence of absent HEVC support. Keep its native logs
and do not weaken process ownership or admit another encoder over a pending stop.

The short server observer did not capture that earlier transient invalidation;
the cooldown defect is proven by the regression cases, rather than a claim that
all observed availability failures have a single established cause.
