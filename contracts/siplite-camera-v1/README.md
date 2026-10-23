# Negotiated siplite camera contract

Revision `siplite-camera/1.0.0`, 2026-10-23. Contract and offline vectors only;
deployed reader/writer support and camera/browser E2E must be verified separately.

`hevc.schema.json` extends frozen `hevc-contract/2.0.0` without changing it.
`camera-rpc.schema.json` is canonical in IoT; `local-camera.schema.json` is the
stable device API contract mirrored here for integration. The complete package
is byte-identical in etranprocessing and IoT; `manifest.json` pins every file.

## Negotiation and compatibility

New readers must support `X-L4-Camera-Contract: siplite-camera/1.0.0` on service
capabilities/start/health/renew/stop. Without it, responses and admission retain
the existing frozen v2 projection. Unknown revisions return422 unsupported.
An existing extended session cannot be down-projected: health/renew/stop without
its negotiated header return422; lease watchdog cleanup still runs internally.
The header is not authority: ordinary service authentication/lease checks apply.

Negotiated capabilities return `camera_contract_revisions` and `camera_formats`.
Do not infer support from a200, image version or global h265 list. A camera
descriptor using expanded limits must have `source_type=camera`,
`profile_id=default`, `camera_contract_revision=siplite-camera/1.0.0` and a single
concrete video track. Every subsequent operation preserves that revision and
the same immutable descriptor/epoch. Frozen camera descriptors remain valid
within their original limits; desktop/usb-camera/test cannot opt into the new
camera branch. New camera fields must never reach an old writer without negotiation.

The camera branch represents Main8/420 HEVC, main-tier level30..153 using the
explicit enum, or H.264 baseline/main/high with matching SPS profile_level_id.
Initial raster envelope is even2..2592 ×2..1944; max30 integer FPS, at most20
above1920 width or1080 height. These are bounded contract representations for
the investigated sensor, not an assertion that every combination decodes.
Camera schema, relay, active server format and browser readiness must all agree.
Main10, B-frames, DONL/interleaving and additional tracks remain unsupported.
Level metadata is copied honestly from parameter sets, never rewritten.

## Selection before START

Camera Auto selects H.265 when all four fresh capabilities (camera, relay,
server/Janus, browser) are ready; it selects H.264 only on confirmed unsupported
H.265 and ready H.264 across the chain. Unknown/auth/timeout does not mean
unsupported. Explicit H.265 never falls back. Once media prepare/START fixes the
concrete descriptor, codec is immutable for that stream. Runtime failure ends
the attempt; new manual START requires fresh authority. Desktop Auto is unchanged.

## RPC and local API

Methods160..164 retain their roles. Extension165 performs port-2 discovery,
166 manages the binding/credential profile, 167 controls/commissions verified
illumination. All cloud operations complete with RES and correlated gauge84,
no new event type and no STM32 command. New envelopes require advertised camera
contract support; old firmware must not receive them.

POST `/local/rpc` uses the same method/controller and accepts the `local_rpc`
definition. Session/PIN/hardware_id checks happen before parsing or mutation.
POST returns202 `local_operation`; poll GET
`/local/camera/operations/{operation_id}` for terminal status. GET
`/local/camera` returns `camera_snapshot`, including safe capabilities and actual
track when known. Local work completes without MQTT; cloud publication status
is separate. These endpoints are permanent versioned interfaces for l4siplite.

Local request limit8192 bytes/depth12; snapshot ≤32768, operation/RES ≤4096.
Cloud camera payload ≤8192. `camera_id` defaults to `cam:ip000001`. Timeout
defaults: read20000 ms, writes/discovery30000; range1000..30000. RPC164 retains
1000..15000 and its existing fixed power-cycle semantics. One monotonic deadline
includes queue/auth/HTTP/parse/readback and is capped by remaining task TTL.
Use TTL of at least one minute for long probes; do not extend it on retries.

The top-level local operation_id, an inner operation_id when present, the sealed
credential operation_id and cloud correlation/task UUID must agree. Duplicates
return a saved result; same operation with different content is409. No blind
retry of toggles, writes, power restart or probe. Persist a credential-operation
receipt atomically with its profile; RAM-only dedup is insufficient across reboot.
Discovery cancel uses a new operation_id and target_operation_id of the active
scan. Illumination commands each use a new operation_id; commissioning_id groups
probe/confirm/cancel into one bounded session. Replays of the same command are
deduplicated, while a new confirm/cancel is a distinct command.
Completed/cancelled replay
is harmless. Other concurrent writers return409 busy under the same camera guard.

Machine schema validates shapes; runtime additionally validates byte sizes,
candidate ownership, revision, board permissions, TTL and cross-field identity.
Unknown object fields and duplicate JSON keys are rejected before execution.

## Credentials

Cloud166 accepts `sealed_credentials`, never plaintext user/password. The caller
obtains the authoritative current device RSA certificate from the trusted device
registry, checks its SN/validity/revocation and seals with that key. Gauge-supplied
keys are not authority. No valid supported recipient key means an explicit
failure; there is no plaintext cloud fallback.

RSA2048/3072/4096 OAEP-SHA256, MGF1-SHA256, label bytes
`siplite-camera-credentials/v1` wrap a fresh random256-bit AES key. A fresh96-bit
nonce and A256GCM produce ciphertext and a128-bit tag. Binary values use canonical
standard base64 with padding. AAD is ASCII JSON containing exactly HEADER from
`credential_reference.py`, keys sorted, separators comma/colon, no whitespace.
The plaintext is UTF-8 JSON with exactly username/password; limits64/128 UTF-8
bytes, no control characters, no colon in username. Envelope deadline is at most
60 seconds ahead and within the task deadline; invalid device time rejects it.
Bind SN, certificate SHA256(DER), operation ID and deadline before decrypting.

Only ciphertext can enter task storage/history. Redact the entire credential
envelope from logs/audit/results too; never echo its contents. BFF receives
plaintext only over an authorized HTTPS write-only endpoint, seals before IoT,
does not persist it and never forwards it to media/Janus. Local166 instead uses
`credentials` under an authenticated LAN session; it is excluded from logs and
generic readback. The reference is an interoperability oracle, not a claim of
zeroization in Python; device implementation must erase temporary buffers.

Store an atomic versioned private credential-profile blob via common NVS handler;
generic NVS49/50, export and diagnostics cannot read/write its secret fields.
Migrate existing cfg_cam/user/password only when both are valid, commit new blob
before retiring old keys. A corrupt/partial profile fails explicitly; clearing
custom credentials returns to the native factory profile installed through
private provisioning. No firmware factory password is published in this package.

## Evidence and verification

Native fields in `native_hevc_level51` come from archived2026-10-22 camera SPS:
2592×1944, Main8/420, profile_space0/profile_id1/tier0/level153. Its UUIDs,
deadlines and other fields are synthetic; it is not a live START or proof of
keyframe cadence. Gated capture and real decode remain required.

Run `python verify.py` with requirements installed. It checks the camera/RPC/local
vectors, the unchanged baseline corpus and definitions, Auto decisions, envelope
roundtrip and tamper rejection. It does not operate a camera or deploy a server.
