# 18C IoT compatible production rollout

Producer verification: **ACCEPTED**. Independent controller acceptance is
pending; this report does not open 18D. Final candidate is
`docs/l4desk/handoffs/L4D-18C-IOT-FIX-01-candidate.md` (DETACHED_V1).

## Scope and contract gate

- Owner: `iot-rpc-rest-app`; branch `l4desk/l4d-18c-iot`.
- Registration: `R-L4D-18C-IOT-FIX-01-v1`; prompt `L4D-18C-IOT-FIX-01`.
- Direct inputs: accepted `H-L4D-18B-PB-v1` (sequence gate, producer
  `67827b607e64d771e368a0a43e1b6c0f09087dd8`) and
  `H-L4D-18C-IOT-EVIDENCE-CONTRACT-01-v1` (data-only export
  `e7a03f8e089537fd91fcaad62659ffdd2c349515`), both version 1.0.0.
- Controller packet `b11acd74b2c753d3488354cf85ecba1a58fa49a8`:
  25 file digests / 22 granted artifact digests verified, no revocation.
  Exact input paths and Git/raw hashes remain in
  [input manifest](evidence/18c-preparation/input-manifest.json) and
  [gate evidence](evidence/18c-preparation/18c-contract-gate.json).
- Consumers: `L4D-18D-MEDIA`, `L4D-18E-MB`.

## Implementation and deployment

Baseline: `60f7762ec766e432bf372e255e94fdd33d3d91d2`, schema
`0008_org_reservations`. Preparation changes and complete classification of
the 75 Python file edits are documented in
[preparation report](L4D-18C-IOT-FIX-01-preparation.md).

Published implementation:

1. `ed7caa4021872b9d89068fe5195ffb5a96de0791`: existing quality-gate repairs;
   43 Python files have identical ASTs, 32 contain reviewed lint/import/ORM
   corrections. No migration operations changed.
2. `a47f4e54ae5b5e791f513e4c4bd9e3df0b17083e`: private build-context exclusion,
   removal of tracked historical env backup, safe template, pinned Python/uv,
   provenance labels and explicit-commit deployment runbook.
3. `35f1fce054e388a2206af45f1416b9572b0614a9`: Dockerfile includes exactly
   the repository-owned archive manifest schema and examples at the runtime
   path expected by the existing archive module. No Python/contract edits.

The initial Linux image revealed a real packaging defect: three archive tests
failed because the schema existed in the checkout but was absent from the
image. After the third commit all 24 selected Linux functional tests passed.

Final source: **35f1fce054e388a2206af45f1416b9572b0614a9**, pushed to origin.
Source archive SHA-256:
`6401058dc075164d660aaf38c686c05939e6737a9f7ba59f685ad7992781081e`.
Final production image:
`sha256:d2540c3e7c5da54077a0543491a6b0bb0782244c9837d7430b218bbf730568ba`.
Runtime started **2026-09-27T20:38:47.480096655Z**.
207 application/contract files match the raw Git archive. Package is 0.1.1;
schema remains `0008_org_reservations`, startup migration was a no-op.

Deployment used the normal production-host build and
`sudo docker compose up -d --no-deps --no-build app1`, after explicit checkout
of the published commit. Build arguments bind source revision and archive hash.
No changes to PB, MB, media, brokers, nginx or Agent 1.8.2-beta-1. All twelve
other containers retained their IDs, images and start times.

MCP Ops tools unavailable; approved SSH fallback used. Before work: about
16 GiB available disk, 1.9 GiB available RAM, low load. Only the production
host was deployed; the separately authorized test host remained a build host.

## Security and backup

No private env/key payload found in the new image. All twelve production
APP_CONFIG settings were present and equal to the private env file, checked
before and after deployment without exposing values. The owner confirmed
that historical credentials in the removed backup had been replaced/revoked;
file deletion is not claimed as rotation or history erasure.

The host's PostgreSQL 16 tools were unsuitable for PostgreSQL 18.4. Backup used
the pinned PostgreSQL 18 client image, a temporary mode-600 credential file
removed in `finally`, and `pg_dump --format=custom --no-owner --no-acl`.
Archive: 481957 bytes; SHA-256
`749bcf6245566b2b022b4000ce322feb1c7d4b9b6fb411c13307d1f07406bb01`.
`pg_restore --list` succeeded with 248 TOC entries. Config and compose backups
are private on the production host. No database restore exercise was run.

## Checks and evidence

| Check | Result and scope |
|---|---|
| Full local suite | 431 passed, 4 existing warnings; preparation before/after quality repairs |
| Ruff / Black | Ruff 0.15.5 pass; Black 26.5.1 pass, 192 files; Pyright not configured |
| Final image lock/stop/archive tests | 24 passed, 3 warnings; isolated container, network disabled, synthetic data |
| Supported older Agent provider contracts | 15 passed against authorized packet vectors; nine historical external digest cases deselected and replaced by the finite gate |
| Current accepted Agent | Operator confirmed moving video and normal stop, including a second 10–15-second check after final image installation |
| API / Redis / schema | docs 200, authenticated event feed 200, Redis PING true, schema 0008 |
| Auth negative | unauthenticated event feed 403 |
| Feed resume | cursors 487/488 then 489/490; repeated first page identical; strictly-after semantics |
| Existing provisioning | test device lookup 200, tenant 10000, status provisioned, contract 1.0.0 |
| Actual API mutual exclusion | console create 201 active; replay same ID; competing video 409 session_busy |
| Actual API stop | 200 closed; repeated stop retains closed_at; no terminal command executed by this provider-state probe |
| Graceful console response / timeout | both branches pass in isolated final-image tests; no actual terminal command asserted |
| Actual archive dry-run | one synthetic event for existing tenant 10000, May timestamp; purge=false, real DB transaction rolled back |
| Archive independent reread | gzip record count 1 and SHA-256 match; temporary staging removed; no probe batch/session persisted |
| Cursor guard | 100/99 rejected, 100/100 accepted; synthetic guard values, not a claim of consumer acknowledgement |
| Queue backlog | 40 queues, 37 countable; ready=0 and unacknowledged=0; three QoS0 queues have no counters |
| Integrity metrics | duplicate active SN=0, duplicate event IDs=0, orphan session events=0 |
| Runtime | no restart and no startup/runtime traceback in container log window |

Image test command:
`sudo docker run --rm --network none --memory 1g --cpus 1 --entrypoint python user1-app1 -m pytest -q tests/core/test_l4d_07_session_lock_and_graceful_stop.py tests/core/test_l4d_15b_archive.py`.
The provider vector harness redirected only the test fixture path to the
authorized immutable export; it did not read excluded neighboring sources.

Sanitized results and test output are in [rollout evidence](evidence/18c-rollout/).
Browser observations are operator attestations, not automated browser traces.
The operator reported "норм, трансляция работает", then "без ошибок" for stop,
and "все хорошо" after final-image start/stop. The final attestation followed
the recorded 20:38:47 UTC container start on 2026-09-27; an exact browser action
timestamp was not collected.

## Rollback and limitations

Rollback image is retained as `user1-app1:18c-pre-a47f4e5`:
`sha256:29aa88169ab8b051705044f0feb1ad8b4d5af5827bcef5294b437c7e29b9c431`.
To roll back, verify this ID, tag it as `user1-app1`, then recreate only app1
with `--no-deps --no-build`; restore the old source checkout for subsequent
builds. Schema is unchanged; a database restore is not required for image
rollback. Readiness verified; no production rollback/re-upgrade was exercised.

Archive worker remains disabled. An empty historical month rejects an empty
`record_types` list under the current manifest schema; this was observed,
rolled back and is not presented as a successful empty archive. The positive
dry-run used a synthetic record in an explicitly rolled-back transaction.
The dry-run implementation does not itself perform the full verifier: this
probe independently reread gzip and recomputed SHA-256. Production purge,
long-term retention, external storage durability and real restore are not claimed.

Two pre-existing requested sessions (IDs 104 and 158, dated September 23 and
25, without start/heartbeat) were recorded before deployment and left intact.
They are not new deployment orphans. Old Agent compatibility is contract-level,
not a separate physical old-terminal test. Provisioning was a lookup of the
existing device; no new tenant, PIN or enrollment was created.

The archive synthetic transaction consumes sequence values despite rollback;
cursor gaps are valid. Internal API smoke leaves its closed audit session and
events intentionally. Temporary credential files and archive staging were
removed; private rollback evidence and pinned source archives remain for recovery.

Known non-blocking warnings are FastStream integration deprecation, two
Pydantic class-config deprecations and the earlier Windows AsyncMock warning.
There are no protocol changes or destructive archive actions in this rollout.
