# File manager control — local implementation handoff

2026-10-05; baseline origin/master 8c2be80; feature/file-manager working tree, no commit/deploy.
The original checkout and its dirty documents were preserved. This isolated checkout contains FM changes.

Files scope uses the existing common memory/Redis lease registry, excludes console/stream/input/view
including the same owner, and cannot be upgraded/touched through generic remote-input endpoints.
Revoked files lease keeps its active slot until original expiry + 5 seconds. Redis WATCH on both
hash/active key prevents stale touch/revocation resurrection; tenant/device/session must match.

New strict internal service-authenticated /api/internal/v1/file-manager routes reserve lease then
signal start/renew/stop/list/transfer/cancel through existing DeviceTasksService MQTT tasks.
7020 list, 7021 transfer, 7022 cancel, 7023 lifecycle; strict IDs/action/TTL-only dt[0].
No paths, storage URLs or file bytes enter this API. Agent HTTPS goes to ProcessingBackend;
file content only agent–S3–browser. Consumer is l4con extra_service in etranprocessing.

Verification: from repo root uv run --project app-service pytest app-service/tests -q:
536 passed / 7 skipped. Changed source/test ruff and black --check passed.
Initial run from app-service had a docs-path evidence failure; correct root run passed.
Generated schema/fixture rewrites from tests were restored from HEAD in this checkout.
Method registry was updated separately. Real Redis/MQTT/native/S3 E2E and production rollout pending.

Companion etranprocessing implementation includes additive PB schema 032, agent mTLS metadata,
S3 signed SHA256/version grants, native no-overwrite commit/receipt and standalone Classic/L4Desk /files.
Release must coordinate common lease conflicts, consumer schema compatibility, native signing,
provider integrity/lifecycle gates and fault canary. Local tests do not prove live delivery or drain timing.

## Current follow-up: FM v2 only, 2026-10-05

Working branch feature/fm-reliability-explorer, baseline f4cd4128e4f0caa33788918692f97603c6061687.
Previous evidence above describes the original v1 implementation, not the current release candidate.
User explicitly removed the requirement to support FM v1. List/close use separate fmc/fmr with
strict v=2 envelopes, mandatory correlated worker-exit close ACK, no RPC listing/close fallback.
Start/renew and transfers retain RPC 7023/7021 and PB authority. No optional confirmed_close flag.
Redis/memory same-owner reacquire cannot renew files lease; confirmed stop cannot unlock a newer owner.
Selected lease/navigation tests: 22 passed; selected ruff/black passed. No deploy or live broker E2E.
