# H-L4D-17C-VIDEO-WATCH-IOT-01-v1 — provider handoff

```yaml
handoff_id: H-L4D-17C-VIDEO-WATCH-IOT-01-v1
registration_id: R-L4D-17C-VIDEO-WATCH-IOT-01-v1
prompt_id: L4D-17C-VIDEO-WATCH-IOT-01
prompt_type: corrective-provider
scope_project: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
git_branch: l4desk/l4d-17c-video-watch-iot-01
producer_commit: f58dfb5e6ff18f6710282824c91b634fcdf5e378
contract_version: 1.0.0
schema_revision: 2026-09-26-v1
candidate_format: DETACHED_V1
sequence_gate_handoff_id: H-L4D-16-MB-v1
required_handoff_ids:
  - H-L4D-07-IOT-STOP-v1
output_handoff_id: H-L4D-17C-VIDEO-WATCH-IOT-01-v1
next_prompt_id: L4D-17C-IOT
status: READY_FOR_ACCEPTANCE
consumers:
  - L4D-17C-IOT
  - L4D-17C-VIDEO-WATCH-MB
```

## Result

Added `WS /api/internal/v1/remote-input/ws/watch/{sn}` for a tenant-scoped,
read-only video-state invalidation feed. The endpoint requires the configured
internal service key in `X-Internal-Service-Key` and a positive `X-Org-Id`,
checks device ownership before accepting, sends the existing `StatusResponse`
shape as an initial snapshot, and then emits invalidation hints for local
presence and stream events. Consumers re-read the authoritative status after an
event and after reconnecting. The channel accepts no control, keepalive, or
lease command and never mutates a lease.

The provider contract is recorded in
`docs/l4desk/handoffs/L4D-17C-VIDEO-WATCH-IOT-01-contract.md`. The existing
control WebSocket, REST status endpoint, MQTT topics, agent commands, session
lock, stop intent, and database schema were not changed. The event feed carries
stream epoch, state/reason, and timestamp hints; media quality and decoded
frames remain outside the IoT contract.

Subscriptions are process-local. The contract therefore explicitly requires
`WEB_CONCURRENCY=1`; cross-worker fanout remains outside this cascade and must
be handled after L4D. A slow subscriber is closed on send timeout or backlog
over 100 and must reconnect and refresh its snapshot.

## Verification

- `uv run pytest`: **422 passed**, 4 warnings.
- Changed-file `ruff check`: passed.
- Changed-file `black --check`: passed.
- Existing remote-input API regression suite: **9 passed**.
- Published branch: `l4desk/l4d-17c-video-watch-iot-01`.
- Deployment target: `user1@87.242.100.34`, only `app1`, via local image build and
  `sudo docker compose up -d --no-deps app1`.
- Runtime commit: `f58dfb5e6ff18f6710282824c91b634fcdf5e378`.
- Runtime evidence: `Migrations applied!`, one Gunicorn worker, and
  `Application startup complete.`; `WEB_CONCURRENCY=1`.
- Internal smoke selected a device with a valid organization binding and
  received `WATCH_SNAPSHOT_OK=True` from the new WebSocket.
- Post-deploy logs contain no runtime settings dump. A pre-existing settings
  print that exposed credentials was removed in the producer commit.

The first smoke attempt used a device without a valid organization binding and
was correctly rejected with HTTP 403; the positive smoke was then run against a
tenant-bound device. No UI action is required for this provider handoff.

## Rollback

The preceding deployed source was `22a50a186da25dddb19612c475bf9bcbb4a7fab2`.
Rollback is limited to switching the repository to that commit, rebuilding,
and recreating only `app1` with `--no-deps`. The `.env` backup created before
deployment remains on the server. Because the diagnostic command initially
captured the settings representation in tool output, the internal service key
and database/broker credentials should be rotated through the approved
operations procedure; none were committed or included in this handoff.
