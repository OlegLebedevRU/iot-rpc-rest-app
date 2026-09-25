<!-- HANDOFF:H-L4D-17C-VIDEO-WATCH-IOT-01-v1:BEGIN -->
```yaml
handoff_id: H-L4D-17C-VIDEO-WATCH-IOT-01-v1
registration_id: R-L4D-17C-VIDEO-WATCH-IOT-01-v1
prompt_id: L4D-17C-VIDEO-WATCH-IOT-01
prompt_type: corrective-provider
target_repository: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
git_branch: l4desk/l4d-17c-video-watch-iot-01
producer_commit: f58dfb5e6ff18f6710282824c91b634fcdf5e378
report_commit: 00b2433e570e0d7ab72e9a7ed0c50d368acede49
contract_version: 1.0.0
schema_revision: 2026-09-26-v1
candidate_format: DETACHED_V1
detached_candidate_approved: true
candidate_path: docs/l4desk/handoffs/L4D-17C-VIDEO-WATCH-IOT-01-candidate.md
report_path: docs/l4desk/handoffs/L4D-17C-VIDEO-WATCH-IOT-01-report.md
contract_kinds:
  - API
  - EVENT
  - DEPLOYMENT
consumers:
  - L4D-17C-IOT
  - L4D-17C-VIDEO-WATCH-MB
next_prompt_id: L4D-17C-IOT
supersedes: []
status: CANDIDATE
artifact_paths:
  - app-service/api/internal_v1/remote_input.py
  - app-service/tests/api/v1/test_remote_input_api.py
  - app-service/core/config.py
  - docs/l4desk/handoffs/L4D-17C-VIDEO-WATCH-IOT-01-contract.md
  - docs/l4desk/handoffs/L4D-17C-VIDEO-WATCH-IOT-01-report.md
artifact_sha256:
  - 114c47172d24a8960bab33da02cece705102d1b7865678b167a8270126054879
  - cd5a6c8d85878df2244beb4122ac354af4bf13636a2328519dd3e0556e54ff06
  - 21f6290b0d2c4cfa6347e28e4abc55278f60364fab3f4a2cb7c32b51aa13784e
  - ef924d9992b4d319e3a876f01834175ba3fb8b2438698cfb289ccaed40bd5e42
  - 74931528a2753f34f752ebce3e707b65e5c35edf903e60b071dc068b3503623f
contract_payload:
  watch_ws_path: /api/internal/v1/remote-input/ws/watch/{sn}
  auth: X-Internal-Service-Key header plus positive X-Org-Id ownership check
  mode: read_only_invalidation_feed
  initial_message: snapshot
  subsequent_message: invalidate_then_consumer_resnapshot
  local_subscriptions: true
  app1_workers: 1
  cross_worker_fanout: deferred_until_after_l4d
  lease_mutation: false
  mqtt_topic_change: false
  tests_passed: 422
  deployment_status: DEPLOYED_SMOKE_VERIFIED
```
<!-- HANDOFF:H-L4D-17C-VIDEO-WATCH-IOT-01-v1:END -->
