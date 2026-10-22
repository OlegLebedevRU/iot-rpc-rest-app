# HEVC TASK-00: shared contract pin

Date:2026-10-22. Revision:`hevc-contract/2.0.0`.
Aggregate SHA-256:`f065b967cd10c2c709fb394ef9e6c2ecf74f77de060d88c9a821cc9069766ac4`.

Canonical owner: `OlegLebedevRU/etranprocessing`,
`docs/etran_arch-hevc-contracts.md` and `docs/etran_arch-hevc-media-siplite-contract.md`.
The rollout plan is `docs/etran_arch-hevc-rollout-plan.md` in that repository.
Exact base source SHAs and per-file hashes are in
[manifest](../../../contracts/hevc-v2/manifest.json); local
[package](../../../contracts/hevc-v2/README.md) is byte-identical in all three repos.

Scope: schemas, fixtures, offline verifier and CI; no product code, deploy or MQTT.
Codec is immutable per stream; HEVC failure terminates, with no fallback/restart.
Existing single-active-lease-per-SN and input exclusivity remain unchanged.
No independent multi-viewer admission or audio implementation is authorized here.

Owner responsibilities: IoT—CTL/lease/typed inventory; l4tools—native/IPC/probe;
l4media—descriptor/Janus/Redis; MenuBuilder—BFF/UI/legacy projection.
Profile IDs are `default` and `low`; old native IPC START stays70bytes.
All new v2 readers/writers and real handlers are deferred to later tasks.

Validate offline using the command in the package README. CI pins this same digest;
editing only a schema, fixture, copy, manifest or CI pin must fail verification.
Changing the contract requires a coordinated revision/pin update in all repos.
The verifier also accepts `--peer` paths to compare checkouts without network access.

Checks and limitations are recorded in the etranprocessing handoff
`.agent-context/tasks/active/2026-10-22-hevc-contracts-p0.md`. This packet is not
G-SERVER-READY; no live Janus/browser/GPU evidence was collected.
Rollback P0 by reverting only this task's added contract/docs/CI/index entries;
there is no runtime state to drain. Later HEVC rollout requires drain before an old
reader rollback, as specified in the canonical contract.
