# Handoff Report: Приёмка device/RPC-контура (L4D-17C-IOT)

## Candidate H-L4D-17C-IOT-v1

```yaml
handoff_id: H-L4D-17C-IOT-v1
status: ACCEPTED
contract_kinds:
  - REPORT
  - DEPLOYMENT
producer_prompt_id: L4D-17C-IOT
producer_scope_project: iot-rpc-rest-app
producer_report_path: docs/l4desk/handoffs/L4D-17C-IOT-report.md
producer_branch: l4desk/l4d-17c-iot
producer_commit: 9cdd740
accepted_at_utc: '2026-09-25T20:30:00Z'
contract_version: 1.0.0
schema_revision: 2026-09-26-v1
artifact_version: 0.1.1
artifact_paths:
  - docs/l4desk/handoffs/L4D-17C-IOT-report.md
  - docs/l4desk/handoffs/L4D-17C-VIDEO-WATCH-IOT-01-contract.md
  - app-service/api/internal_v1/remote_input.py
  - app-service/tests/api/v1/test_remote_input_api.py
  - app-service/core/config.py
artifact_sha256:
  - ef924d9992b4d319e3a876f01834175ba3fb8b2438698cfb289ccaed40bd5e42
  - 114c47172d24a8960bab33da02cece705102d1b7865678b167a8270126054879
  - cd5a6c8d85878df2244beb4122ac354af4bf13636a2328519dd3e0556e54ff06
  - 21f6290b0d2c4cfa6347e28e4abc55278f60364fab3f4a2cb7c32b51aa13784e
compatibility:
  backward_compatible_with:
    - H-L4D-17C-VIDEO-WATCH-IOT-01-v1
    - H-L4D-07-IOT-v1
    - H-L4D-15B-IOT-v1
    - H-L4D-06B-IOT-v1
    - H-L4D-02-IOT-v1
    - H-L4D-01C-DOCS-v1
  breaking_changes: false
  notes: >
    Integrated acceptance device registry/provisioning, Agent adapter,
    event feed, session lock/graceful stop, archive worker и video-watch
    invalidation feed. WEB_CONCURRENCY=1; lease mutation forbidden;
    MQTT unchanged. Digests video-watch provider = candidate MATCH.
checks:
  sequence_gate: PASS
  deployed_versions: PASS
  full_local_suite: PASS
  provider_fixtures: PASS
  archive_dry_run_restore_cursor_nopurge: PASS
  production_safe_smoke: PASS
  event_lifecycle_metrics: PASS
  contract_digests_video_watch: PASS
  ruff_changed_files: PASS
  web_concurrency_invariant: PASS
  lease_mutation_forbidden: PASS
  mqtt_unchanged: PASS
deployment_status: ACCEPTED
deployed_environment: production
feature_flags:
  web_concurrency: "1"
  cross_worker_fanout: deferred_until_after_l4d
  video_watch_read_only: enabled
supersedes: []
known_risks:
  - "Video-watch subscriptions are process-local; cross-worker fanout deferred until after L4D cascade"
  - "Slow watch subscriber closed after backlog >100 or send timeout; must reconnect and resnapshot"
  - "Full-repo ruff has 117 pre-existing issues; changed-file ruff is clean"
consumers:
  - L4D-17D-MEDIA
next_prompt_id: L4D-17D-MEDIA
```

---

## 1. Sequence gate

| Handoff | Статус |
|---|---|
| `H-L4D-01C-DOCS-v1` | ACCEPTED |
| `H-L4D-02-IOT-v1` | ACCEPTED |
| `H-L4D-06B-IOT-v1` | ACCEPTED |
| `H-L4D-07-IOT-v1` | ACCEPTED |
| `H-L4D-15B-IOT-v1` | ACCEPTED |
| `H-L4D-17B-PB-v1` | опубликован `bc4ec6c` (etranprocessing) |
| `H-L4D-17C-VIDEO-WATCH-IOT-01-v1` | READY_FOR_ACCEPTANCE → принят данным шагом |

Ветка: `l4desk/l4d-17c-iot` @ `9cdd740` (база `l4desk/l4d-17c-video-watch-iot-01`).

---

## 2. Deployed versions / contracts / digests

| Параметр | Значение |
|---|---|
| Runtime commit | `f58dfb5` (producer) / `9cdd740` (HEAD, candidate) |
| Image | `user1-app1`, created 2026-09-25T21:06:14Z |
| App version | `0.1.1` |
| `WEB_CONCURRENCY` | `1` (подтверждено в runtime env) |
| Gunicorn workers | 1 (UvicornWorker, booted pid 8/48/93) |
| Migrations | `Migrations applied!` |
| Startup | `Application startup complete.` |

### Digests video-watch provider = candidate

| File | SHA-256 | Match |
|---|---|---|
| `app-service/api/internal_v1/remote_input.py` | `114c4717…6054879` | YES |
| `app-service/tests/api/v1/test_remote_input_api.py` | `cd5a6c8d…54ff06` | YES |
| `app-service/core/config.py` | `21f6290b…13784e` | YES |
| `docs/l4desk/handoffs/L4D-17C-VIDEO-WATCH-IOT-01-contract.md` | `ef924d99…0bd5e42` | YES |
| `docs/l4desk/handoffs/L4D-17C-VIDEO-WATCH-IOT-01-report.md` | `74931528…03623f` | YES |

### Video-watch contract invariants

| Инвариант | Статус |
|---|---|
| Snapshot on connect | соблюдён (contract + tests) |
| Invalidate → REST resnapshot | соблюдён |
| Lease mutation | **forbidden** (contract + `test_read_only_watch_…rejects_commands`) |
| MQTT changes | **none** |
| Cross-worker fanout | deferred until after L4D |
| `WEB_CONCURRENCY=1` | runtime confirmed |

---

## 3. Full local suite

```text
cd D:\work\iot.leo4.ru\iot-rpc-rest-app
uv run pytest -q
```

**422 passed, 4 warnings** (51.04 s) — совпадает с provider report.

| Check | Результат |
|---|---|
| pytest | 422/422 PASS |
| ruff check (changed files) | All checks passed |
| ruff check (full app-service) | 117 pre-existing (не из video-watch) |

---

## 4. Provider fixtures (targeted)

```text
uv run pytest app-service/tests/core/test_l4d_01b_agent_contract_v1.py \
  app-service/tests/core/test_l4d_06b_device_provisioning_contract.py \
  app-service/tests/core/test_l4d_02_event_feed_full.py \
  app-service/tests/core/test_l4d_07_session_lock_and_graceful_stop.py \
  app-service/tests/core/test_l4d_15b_archive.py \
  app-service/tests/api/v1/test_remote_input_api.py
```

**77 passed** (33.32 s).

| Область | Ключевые тесты | Verdict |
|---|---|---|
| Agent compatibility | `test_l4d_01b_agent_contract_v1` | PASS |
| Provisioning idempotency | `test_l4d_06b_device_provisioning_contract` | PASS |
| Durable cursor / replay | `test_l4d_02_event_feed_full` | PASS |
| Simultaneous console/video rejection | `test_mutual_exclusion_console_blocks_video_and_video_blocks_console` | PASS |
| Lifecycle events | `test_lifecycle_transitions_ordering_and_billable_interval` | PASS |
| Console response / timeout stop | `test_console_command_aware_graceful_stop_with_response/_with_timeout` | PASS |
| Video stop | `test_video_stop_control_flow` | PASS |
| Session lock / row lock | `test_stop_uses_row_lock_and_replay_does_not_repeat_teardown` | PASS |
| Video-watch auth/tenant | `test_read_only_watch_requires_auth_and_tenant` | PASS |
| Snapshot/invalidate/reject cmds | `test_read_only_watch_snapshot_invalidation_and_rejects_commands` | PASS |
| Backlog close | `test_read_only_watch_closes_backlogged_subscriber` | PASS |

---

## 5. Archive dry-run / restore / cursor guard / no-purge

| Check | Test | Verdict |
|---|---|---|
| Contract digests / schema | `test_contract_digests_and_schema_validation` | PASS |
| Secret scrubbing | `test_deterministic_serialization_and_secret_scrubbing` | PASS |
| Retention boundary | `test_retention_boundary_guard` | PASS |
| Cursor guard / lag | `test_cursor_guard` | PASS |
| Path security | `test_path_security_guard` | PASS |
| Full lifecycle + No-Financial-Purge | `test_full_archive_lifecycle_and_no_financial_purge` | PASS |
| Crash phases + no-purge-on-failure | `test_crash_at_every_phase_and_no_purge_on_failure` | PASS |
| Archive API endpoints | `test_internal_v1_archive_endpoints` | PASS |

Production details **не удалялись** (acceptance read-only).

---

## 6. Production-safe smoke (redacted)

**[MCP Ops Readiness: READY]** (SSH fallback): load healthy, RAM ok, disk 81%.

Только IoT interfaces. Test identifiers (`SMOKE17C`, `000100773`). Credentials/PIN не раскрыты.

| Probe | Ожидание | Факт | Verdict |
|---|---|---|---|
| `GET …/devices/SMOKE17C/status` invalid key | 403 | `Invalid internal service credentials` | PASS |
| `GET …/devices/000100773/status` valid key, unbound org | 403 | `device not available for organization` | PASS |
| Positive snapshot (provider smoke) | snapshot | `WATCH_SNAPSHOT_OK=True` (H-L4D-17C-VIDEO-WATCH report) | PASS |

Только error-path + provider positive evidence. Активных lease/stream не создавалось.

---

## 7. Metrics

| Метрика | Значение | Источник |
|---|---|---|
| Tests | 422 passed | full suite |
| Targeted fixtures | 77 passed | §4 |
| Start-stop lifecycle | covered | `test_lifecycle_transitions_ordering_and_billable_interval` |
| Console/video mutual exclusion | covered | mutual-exclusion tests |
| Orphan/duplicate handling | covered | `test_stop_uses_row_lock_and_replay_does_not_repeat_teardown`, `test_duplicate_operations_idempotency` |
| Stale session eviction | covered | `test_crash_recovery_stale_session_eviction` |
| Event lag (cursor) | covered | `test_cursor_guard` + `test_l4d_02_event_feed_full` |
| Runtime workers | 1 | `glogging: Booting worker with pid: 8` |

---

## 8. Rollback

| Параметр | Значение |
|---|---|
| Preceding commit | `22a50a1` (remote session stop durable) |
| Procedure | checkout `22a50a1`, rebuild image, `sudo docker compose up -d --no-deps app1` |
| Scope | only `app1` (`--no-deps`) |
| `.env` backup | preserved on server |
| Destructive changes in this acceptance | none |

---

## 9. Воспроизводимые команды

```powershell
cd D:\work\iot.leo4.ru\iot-rpc-rest-app
git switch l4desk/l4d-17c-iot   # HEAD = 9cdd740

uv run pytest -q
uv run pytest app-service/tests/core/test_l4d_01b_agent_contract_v1.py `
  app-service/tests/core/test_l4d_06b_device_provisioning_contract.py `
  app-service/tests/core/test_l4d_02_event_feed_full.py `
  app-service/tests/core/test_l4d_07_session_lock_and_graceful_stop.py `
  app-service/tests/core/test_l4d_15b_archive.py `
  app-service/tests/api/v1/test_remote_input_api.py -q
uv run ruff check app-service/api/internal_v1/remote_input.py `
  app-service/tests/api/v1/test_remote_input_api.py app-service/core/config.py
```

---

## 10. Вердикт

**`ACCEPTED`** — все checks зелёные.

- Full suite **422 passed**
- Provider fixtures **77 passed**
- Archive dry-run / restore / cursor / no-purge **PASS**
- Production-safe smoke **PASS** (auth + ownership + provider snapshot)
- Video-watch digests = candidate, invariants соблюдены
- `WEB_CONCURRENCY=1`, lease mutation forbidden, MQTT unchanged
- Consumer: `L4D-17D-MEDIA`

Acceptance-код не менялся. Commit/push — только данный отчёт.
