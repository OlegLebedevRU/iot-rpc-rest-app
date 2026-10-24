# Proposed camera monotonic CTL extension

Revision: `camera-ctl-monotonic/0.2.0-proposed`. **Review only; no runtime support
or deployment implied.** Normative candidate semantics and ownership:
[server agreement proposal](../../docs/camera-ctlv1-monotonic-agreement.md).

`camera-ctl.schema.json` defines a separate strict wire candidate, without editing
frozen CTLv1, HEVC2.0 or siplite-camera/1.0.0 schemas. `vectors.json` contains
synthetic stateful conformance scenarios. `verify.py` is an offline oracle only;
production modules do not import it. Shape validation cannot prove authentication,
physical binding, lease ownership or monotonic clock continuity.

Run from repository root:

```powershell
uv run python contracts/camera-ctl-monotonic-v1/verify.py
```

The verifier checks all message shapes, unknown fields, duplicate keys, required
correlation, issuer intervals and stateful admission/replay/deadline vectors.
No camera, MQTT, network or production state is accessed.

The corrected revision adds admission_seq shared by every message. It replaces
whole-boot receipts with high-water replay rejection plus bounded recent response
caches. verify.py keeps one terminal alive through10000 renewals and10000 new
attempts. review-reproduction.json preserves the old0.1 failure evidence.
descriptor-hash-vectors.json provides RFC8785 canonical UTF-8 hex and SHA-256
for cross-language consumers; the integer-only numeric domain is defined in the
proposal, not presented as a general JCS implementation.
