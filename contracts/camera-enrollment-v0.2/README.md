# Complete camera enrollment 0.2 candidate

This new package selects only the full Native Auto bundle: camera1.1,
camera-cadence0.1, enrollment0.2 and admission0.2. All gates remain off.
Frozen enrollment0.1 and admission0.2 artifacts remain unchanged.

`schema.json` resolves `urn:leo4:siplite-camera:1.1.0` to
`../siplite-camera-v1.1/hevc.schema.json` and
`urn:leo4:camera-admission:0.2.0` to
`../camera-ctl-monotonic-v1/camera-ctl.schema.json` through an explicit registry.
The media resource is the byte-identical MenuBuilder PR111 package at
`60a2bffc961dfc31caeea96a76bfb856484212b5`. `manifest.json` pins schemas and
fixtures; `../siplite-camera-v1.1.lock.json` pins every imported owner file.

Hello declares camera and cadence support in addition to supported CTL revisions.
Offer includes the full descriptor and full boot binding, revision markers,
binding hash, challenge, issuer generation/epoch and floor. Proof repeats every
offer field except message type and adds the live admission high water. Commit
repeats proof except type and may raise its floor. Commit floor must be at least
max(accepted offer floor, proof high water, server counter for the same boot).
A rejected low-floor commit leaves the pending offer intact.

Firmware first validates physical port2, verified MAC/auth, discovery and device
geometry generations, actual track and cadence. It computes descriptor SHA-256
and then full binding SHA-256. Both revision markers enter the descriptor hash.
The server-chosen descriptor UUID is accepted through this fresh authenticated
exchange. The device does not guess it or trust an opaque digest.

The original 5-second enrollment budget is never refreshed by duplicates.
The wire limit is 4096 UTF-8 bytes and depth8. Full fixture sizes/depths are in
`fixture-bounds.json`; offer/proof/commit are 1588/1614/1615 compact bytes.
Admission remains bound through descriptor SHA-256. Readiness remains 5 seconds
and each lease remains at most 60 seconds.

Run `uv run python contracts/camera-enrollment-v0.2/verify.py`. It independently
checks physical substitutions, complete fixtures, original deadline and the
floor100→commit42 rejection. Runtime tests cover actual durable transitions,
takeover, replay and long renewal.

`verify_c.py` extracts coordinator C code and its host harness from firmware
commit `b165b4da88da66da0411643f74b080a272e40653`, builds with `-Werror` and links
actual SDK MbedTLS SHA-256. It compares canonical bytes and digests for descriptor,
binding and all three full messages. See `c-canonical-report.json`. Reproduce
with `--firmware-repo`, `--mbedtls-dir` and `--cc` pointing to the local checkout,
SDK and compiler. Offline checks do not establish real-device/video acceptance.
