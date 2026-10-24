# Full-offer camera enrollment 0.3 proposal

This new proposal is a versioned adaptation of the full-offer0.2 state machine
to the frozen unified `l4-media/3.0.0` descriptor. It does not edit or reinterpret
frozen enrollment0.1/0.2, camera1.0/1.1, monotonic admission0.2 or media3 schemas.
This packet is not evidence of runtime deployment or hardware acceptance.

Exact bundle:
- common media `l4-media/3.0.0`;
- observation/HTTP adapter `siplite-camera/1.2.0` (owned by MenuBuilder);
- cadence `camera-cadence/0.1.0-proposed`;
- enrollment `camera-enrollment/0.3.0-proposed`;
- admission `camera-ctl-monotonic/0.2.0-proposed`.
Camera RPC/local configuration remain `siplite-camera/1.0.0`.

All four enrollment messages keep the original full-offer0.2 semantics.
HELLO adds exact `media_contract_revisions:["l4-media/3.0.0"]` and selects
camera1.2, cadence0.1 and admission0.2. OFFER/PROOF/COMMIT contain the selected
`media_contract_revision` alongside camera/cadence markers, not inside descriptor.
The descriptor external ref points only at the canonical media3 `$defs/descriptor`;
its `contract_version:3`, profile and all concrete original track fields enter
RFC8785 integer-domain descriptor hashing. Source type must additionally be
camera, and source/MAC/path/geometry/codec must match trusted fresh device facts.
No desktop CTL2 START or Windows capability binding enters this adapter.

`low` and `default` are both quality policies. One confirmed native format may
serve both; a changed profile still changes descriptor/hash and requires a new
attempt. No configuration value or original RTP timestamp is rewritten.

The original exclusive local5000ms enrollment budget never resets on duplicate
HELLO/OFFER/PROOF/COMMIT. COMMIT floor cannot be below the accepted OFFER floor,
proof high-water, current device high-water or durable server high-water.
Only exact matching pending offers may commit. Issuer epoch takeover, retired
boot, authority loss, replay caches and counter preservation retain0.2 rules.
Admission still uses the unchanged R/I0.2 schema and never compares device/server
wall clocks or restarts full TTL on late START.

Wire maximum remains4096 UTF-8 bytes/depth8, separately enforced by readers.
`canonical-vectors.json` contains exact compact bytes/digests of the four messages,
descriptor and binding. `verify.py --strict-bytes` validates pinned schema/fixtures,
external common schema, physical binding mutations, both profile policies,
COMMIT floor100->42 rejection and exclusive deadline equality.

Canonical media schema SHA256:
`b86ca6f066fcdecb09cf7145a7fb23d87b77311a53c7ea04f0fb6e8a905b2818`.
Admission schema SHA256:
`e75e1c7f49f0d0fc68f6720a3c47766ccb4caad83d721b5d1b8aabe3d3b58a0d`.
The new enrollment schema/fixture digests are in `manifest.json`.

Both production gates remain disabled. No merge, deployment, firmware install,
writers or allowlist activation is authorized by this packet.
