# 18C IoT preparation

Status: **PREPARATION_VERIFIED**. This is not the production deployment report,
an accepted `H-L4D-18C-IOT-v1`, or permission to open 18D.

## Scope and inputs

- Owner: `iot-rpc-rest-app`; schema owner: this project's Alembic.
- Worktree/branch: `iot-rpc-rest-app-18c`, `l4desk/l4d-18c-iot`.
- Base: `60f7762ec766e432bf372e255e94fdd33d3d91d2`, matching the audited
  production checkout and 150 application files in the running image.
- Controller registration: `R-L4D-18C-IOT-FIX-01-v1`.
- Published controller packet: `b11acd74b2c753d3488354cf85ecba1a58fa49a8`.
- Direct inputs: `H-L4D-18B-PB-v1` (sequence gate) and
  `H-L4D-18C-IOT-EVIDENCE-CONTRACT-01-v1`.
- All 25 packet files and 22 granted artifacts passed Git/raw digest checks.
  Exact paths, versions of source commits and digests are preserved in
  [input-manifest.json](evidence/18c-preparation/input-manifest.json).
- Contracts, MQTT topics/payloads and the accepted Agent 1.8.2-beta-1 remain
  unchanged. The test build does not use production credentials or services.

## Cleanup and baseline protection

The operator explicitly authorized cleanup on both hosts. Production disk
usage fell from 89% to 45% (about 16 GiB available immediately after cleanup).
Seventeen obsolete named images, dangling images and unused build cache were
removed. Active images and selected rollback/provenance images were retained.
All thirteen production containers continued running without restart.

The separate test host fell from 87% to 34% (about 19 GiB available immediately
after cleanup, before the new build). Eleven unused named images, dangling
images and unused build cache were removed, together with six rotated IoT logs
older than fourteen days and 243 MiB of archived journald records older than
fourteen days. All four existing container IDs, images and start times were
unchanged. No volumes were deleted on either host.

Production `app1` was **not redeployed**. Its preserved baseline image is
`sha256:29aa88169ab8b051705044f0feb1ad8b4d5af5827bcef5294b437c7e29b9c431`;
its schema is `0008_org_reservations`. Archive overrides were absent and the
audited implementation defaults archive processing to disabled.

## Published preparation changes

1. `ed7caa4021872b9d89068fe5195ffb5a96de0791`: restore existing quality gates.
   Seventy-five Python files changed: forty-three have identical ASTs, while
   thirty-two contain reviewed unused-import/lint corrections. Public example
   exports are explicit; eighteen ORM boolean predicates use SQLAlchemy
   `is_()` rather than Python negation. The bare exception handler now catches
   `Exception` and preserves its cause. Existing migrations gained no new
   operations or revision IDs. Full tests passed before and after these edits.
2. `a47f4e54ae5b5e791f513e4c4bd9e3df0b17083e`: exclude private configuration
   from Docker builds, remove the tracked `.env.bak` and its ignore exception,
   clear credential-bearing template fields, pin Python/uv image digests, add
   source provenance labels, and require an explicit release commit in the
   runbook instead of blindly selecting the older `master`.

The operator confirmed that historical backup credentials were already
replaced/revoked. Their values were not logged or copied to the test host.
Deleting the backup is not presented as credential revocation or Git-history
erasure. The twelve production `APP_CONFIG` values from the private env file
were separately verified present and equal in container environment, using
boolean results only. A new deploy must repeat that check.

## Validation and candidate image

| Check | Result |
|---|---|
| `uv sync --locked` | PASS; lockfile unchanged |
| Full local `uv run pytest -q` | 431 passed, 4 warnings, before and after lint changes |
| Ruff 0.15.5, `check app-service` | PASS; baseline had 102 findings |
| Black 26.5.1, `--check app-service` | PASS, 192 files |
| Pyright | Not configured in this project |
| Synthetic Docker directory-context probe | Baseline copied three private canaries; corrected context copied zero; source/template retained |
| Release build-input credential scan | Eleven URL findings reviewed as synthetic config-test fixtures; no private key markers |
| Image source fingerprint | 150/150 application files match the Git/raw source archive |
| Image private filenames | No private env/backup/key files in application payload |
| Linux config/retry tests in candidate, `--network none` | 27 passed, 3 warnings |
| Candidate `alembic heads`, `--network none` | `0008_org_reservations (head)` |

Black is the repository's formatter. The controller clarified this in the
published FIX packet; Ruff formatting is not a second conflicting gate.
Warnings remain: FastStream integration deprecation, two Pydantic class-config
deprecations, and a local Windows AsyncMock warning. No checks were suppressed.

The context regression uses a directory build so Docker CLI applies
`.dockerignore`. A direct tar-to-build diagnostic does not prove filtering and
is not used as acceptance evidence. Git source archives must be extracted
before building from the resulting directory.

Candidate on the authorized test build host:

- Tag: `l4d18c-app1:a47f4e5`.
- Image ID: `sha256:eebf349ff3c46da2b9bb535d775133e41e27bcf69b7838c6d2e44b95b172a723`.
- Revision label: `a47f4e54ae5b5e791f513e4c4bd9e3df0b17083e`.
- Git/raw archive SHA-256: `e7e373adae09ff44e2877ef269849cc34220c64de9030c9a70bd0fc4b2cc8b81`.
- Source/build log retained in the task-specific `18c-a47f4e5` build directory.
  Probe containers and synthetic temporary directories were removed.

## Remaining production gates

1. Repeat production resource, image, private-env, Redis/archive-flag and schema
   checks; preserve the exact current image and make a verified `iot_rpc` backup.
2. Deploy only `app1` through the approved repo-first runbook, with no changes
   to PB, MB, media, brokers, nginx or the Agent. Compare the deployed artifact
   with this source revision/archive; a rebuild can have a different image ID.
3. Perform provider/Agent compatibility, provisioning, event resume, lock,
   graceful console/video stop and safe archive/cursor checks; record queue lag
   and duplicate/orphan counts. Use existing approved test tenants/terminals.
4. Finalize the actual deployment report and detached candidate, then obtain
   independent controller acceptance. No current E2E or production rollback
   exercise is claimed by this preparation report.

Machine-readable evidence: [checks.json](evidence/18c-preparation/checks.json),
[contract gate](evidence/18c-preparation/18c-contract-gate.json),
[context probe](evidence/18c-preparation/18c-context-directory-probe.jsonl),
[change classification](evidence/18c-preparation/18c-python-change-classification.json),
[build manifest](evidence/18c-preparation/18c-build-manifest.json).
