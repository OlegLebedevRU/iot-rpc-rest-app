# TASK-51 server-side orphan video lifecycle

Scope: IoT/app1 only. Native TASK-51 and real-browser acceptance belong to the
next agent. Base `origin/master`: `de8850eec9163642a6eed9be8dae57244e1e50c9`.
Implementation branch: `fix/task51-orphan-video`.

## Provenance and findings

Read the shared plan and TASK-10/20/30/40/50/50Q/51 handoffs in
`D:/.codex/hevc-plan`. On 2026-10-23 production inspection confirmed app1
revision `de8850eec9163642a6eed9be8dae57244e1e50c9`, image ID
`sha256:7d62516e5ad5a93dda2c52a745cae64b9abe46aeb4aefcf4b39a343c7d8bceb7`.
Container `/app/core/remote_input/video_control.py` SHA256 equals the baseline
file: `1a49877afa1ab866658d3fcb8e1496725358f6652a5336a087fe3240a61a9ff8`.
BFF revision is `4fea1612a911d4b88a3e2cf2c61bf58e2c1a8316`; l4media revision is
`dcd3ea1c04a6be1e3fe3047f3d5a3bec8747081d`.

Read-only log aggregation for 01:37..02:05 UTC confirms four stream/start409
and four video-stop409 responses. No stream_event log record establishes
whether the native failed event reached the handler. Do not claim its exact
delivery path was proved. Native capture stopped at01:46:50 and the02:04:50
Redis orphan snapshot are evidence from the incoming handoff, not newly
executed hardware observations. Raw production logs are not included here.

Reproduction identifiers remain in the original private handoff. Do not use
them as a new START epoch.

Confirmed code defects:

- Redis active lease keys expire at the lease deadline, while the lease cleanup
  scans those keys; lease hashes and video documents survive longer. A departed
  worker's publisher can therefore miss revoke/STOP entirely.
- V2 ERROR was rejected when its lease was absent/inactive despite fully
  matching the current publisher epoch. Invalidation removes negotiation but
  leaves LIVE state. A later START sees that LIVE state and conflicts.
- Cached Redis lease reads could overwrite the explicit v2 stream CAS or
  recreate an absent hash. V2 reads now preserve Redis authority.

## Patch and evidence

Six new regressions first failed on the baseline: fresh B START conflicts after
A's lease is missing/expired/revoked; exact ERROR A is ignored after each loss.
They pass with the fix. Additional regressions cover provider STOPPED presence,
new agent capability, duplicate concurrent cleanup, restart generation,
renewal/cleanup WATCH race, revoke/START race, expired READY, stale ERROR,
protection of live publishers and v2 cache reads. Existing repeated STOP,
watcher detach, auth/tenant/session/descriptor and G0 tests remain in force.

Periodic cleanup scans video documents and performs an atomic retirement under
WATCH of video+lease+active-key. Authorized manual START runs the same check.
Only lost lease authority permits retirement. Notifications and STOP retain A's
epoch; B needs a fresh authorized START. Late exact ERROR can terminalize A even
without its lease; READY still requires active authority. A's failure does not
invalidate another agent's capability. No-op checks do not refresh retention.

Local Windows/Python3.14.7 locked environment:

- `uv run pytest -q`:752 passed,7 skipped.
- Changed Python files: `uv run ruff check ...` and `uv run black --check ...` PASS.
- G0 verifier:30 schema fixtures,6 legacy fixtures,24 PREPARE,9 lifecycle,
  61 nested unknown-property mutations and duplicate rejection PASS.
- Frozen contract remains `hevc-contract/2.0.0`, digest
  `f065b967cd10c2c709fb394ef9e6c2ecf74f77de060d88c9a821cc9069766ac4`.
- Full ruff/black still report the identical baseline12 diagnostics/23 files;
  unrelated excluded directories were not modified to silence those checks.
- No schema, database migration, dependency, feature flag or native change.

## Deployment and next agent

Deployment receipt (full accepted source SHA, registry digest, rollback and
health) is recorded in `D:/.codex/hevc-plan/TASK-51-IOT-FIX-HANDOFF.md` after
the release. This document alone is not evidence of deployment or browser decode.
Production delivery must use accepted master -> builder176 -> immutable registry
digest -> existing app1 deployer. Preserve the production flag override. Recreate
only app1, with no dependencies/build; do not change `.env` or sibling services.

The TASK-51 agent should resume an ordinary authorized owner flow for terminal773:
obtain fresh lease/capability/agent identity and manually START with entirely new
stream/operation/descriptor IDs. Verify rising HEVC decoded frames. Repeat native
capture failure, owner navigation/close, expiry/release, and600s preview expiry.
After each loss ensure A terminalizes, B manually starts, and A's delayed
READY/ERROR/STOP/ACK cannot affect B. No automatic restart or H264 fallback.

IoT STOP is server intent, not proof of physical process exit. IoT owns neither
Janus nor media Redis. BFF/l4media must use their existing identity-scoped media
stop APIs and lease watchdog. Their actual route/Janus cleanup and teardown after
owner disappearance require separate integration evidence. If those resources
remain after IoT terminalization, hand that scoped issue to the etran agent;
do not delete Redis keys or stop a different publisher. Full TASK-51 and release
acceptance remain open for the next agent.
