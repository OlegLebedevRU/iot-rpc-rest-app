# Selected-display HEVC capability probe

2026-10-24. Owner authorized fixing the complete MenuBuilder → IoT → l4desk
chain and documenting every changed contract. Source-selection implementation
and local tests are separate from release publication and installed acceptance.

## Problem and ownership

MenuBuilder selected DISPLAY2 on terminal773 (`disp:e1ddc8e3`,1920x1080), while
l4desk measured primary DISPLAY1 (`disp:3580dc5e`,3000x2000). Current inventory
requests reproduced DISPLAY2 → `source_mismatch`, DISPLAY1 → `ready`.
The original v2 inventory command had no source selector. Removing the mismatch
check or relabelling primary evidence would authorize an unmeasured source.

MenuBuilder owns selected source and REST adaptation; IoT owns capability query,
cache, correlation and pending state; l4desk owns exact display resolution and
the bounded capture/encode child. l4capture's existing rectangle probe is reused.
No changes to encoder, media routing, lease authorization or certificates.

## Contract changes: hevc-source-probe/1.0

| Boundary | Change | Compatibility / invariant |
| --- | --- | --- |
| Public MenuBuilder inventory | No payload/path change; existing selected `source_id` now reaches the probe | Existing UI request remains valid |
| MenuBuilder → IoT `GET /api/internal/v1/remote-input/devices/{sn}/video-capabilities` | Optional query `source_id`,1..63 characters; absent by default | Tenant/auth checks retained; BFF sends it only for Windows `disp:` sources |
| IoT → terminal `srv/{SN}/ctl`,v2 `inventory_get` | Optional string `source_id`,1..63 characters; omitted, never null, for old queries | Old requests still accepted; old strict Windows agents need updating before targeted requests work |
| IoT transactional video state | Adds `probe_source_id` for the last probe cooldown; pending already stores the complete command including optional source | Fresh cache must match requested source; a live pending probe is not replaced; a newly selected source can be probed without waiting for another source's cooldown |
| Terminal → IoT capability ACK | No schema change | Explicit-source positive ACK must match requested source; wrong-source ACK cannot complete negotiation |
| Native capability / START | No wire change | Source switch clears old measurement/revision; exact source/raster/geometry/freshness required at START |

Schema: `contracts/hevc-source-probe-v1/inventory_get.schema.json` in all three
repositories. It extends only the inventory command with the optional selector.
The frozen `contracts/hevc-v2` package, revision2.0.0 and digest
`f065b967cd10c2c709fb394ef9e6c2ecf74f77de060d88c9a821cc9069766ac4`
remain unchanged. Native command schema includes this explicit extension; IoT
overlays this inventory definition on its frozen validator without changing the
frozen schema file. Other messages retain their original strict validation.

No new presence feature flag or negotiation version is introduced. The owner
accepted coordinated rollout instead of blocking on old targeted-query readers.
This is an additive runtime extension, not a claim that old frozen validators
accept the new field. Unknown properties, duplicate keys and malformed selectors
remain rejected.

## Native behavior

An explicit selector resolves an exact inventory display, including non-primary
origin, resolution, session, policy and adapter fingerprint. No primary fallback
is allowed for an explicit missing selector. Without a selector, native behavior
retains primary selection. Probes remain Medium-first with the existing deadline,
hardware proof, profile budgets, stable post-ACK snapshot and bounded child Job.
No hardware probe runs alongside an active encoder. A new source discards old
profiles and changes the revision; old START cannot reuse the previous source's
measurement. Missing sources advertise no ready profiles.

## siplite boundary

The backend patches are based on current accepted siplite integration:
etranprocessing `7e5322e`, IoT `0767061`. Preserve the camera branch selected by
`X-L4-Camera-Contract`, its camera capability/lease readers and vault changes.
The BFF forwards desktop selection only for `disp:`; camera/test-camera requests
keep the previous query shape. Camera schemas/descriptors, firmware, media API,
credential handling and `contracts/hevc-v2` files are unchanged by this patch.
This does not establish new physical firmware acceptance.

## Rollout and release

Integrate native support and IoT reader before enabling the BFF's targeted
requests. Deploy through each repository's ordinary release procedure; retain
current operator overrides and arrange an idle video window for container
recreation. No server deploy or terminal installation belongs to this handoff.

For a native release use the published1.13.49 signed baseline and selective
`--reuse-receipt`. Only l4desk and the new installer are changed. Reuse every
unchanged signed EXE byte-for-byte with signed metadata, dependency/hash binding
and retained baseline test evidence. Do not rebuild, rerun component tests or
re-sign unchanged EXEs. Validate the new l4desk, installer, package and publication
normally. Do not publish from an unreviewed/dirty source checkpoint.

## Verification and limits

Detailed results and transferable backend patches are supplied in the task's
handoff bundle. Both native architectures and selected-source fixtures pass;
backend tests include current siplite camera readers. Source correctness is
tested by inspecting actual child rectangle/raster arguments, not only ACK labels.

The isolated real-pair attempt from the current process returned
`capture_path_unavailable` for both displays; no positive hardware/decode claim
follows. After integration/release, verify installed source-bound inventory and
actual H265 decoding on both DISPLAY1 and DISPLAY2, switch back, and confirm
H264 compatibility. Preserve that unsuccessful probe evidence. No live service,
installed executable, certificate, firmware or server was changed by these checks.
