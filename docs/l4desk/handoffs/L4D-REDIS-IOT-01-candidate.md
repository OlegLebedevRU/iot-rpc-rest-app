<!-- HANDOFF:H-L4D-REDIS-IOT-01-v1:BEGIN -->
```yaml
handoff_id: H-L4D-REDIS-IOT-01-v1
registration_id: R-L4D-REDIS-IOT-01-v1
prompt_id: L4D-REDIS-IOT-01
prompt_type: implementation-provider
target_repository: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
git_branch: l4desk/l4d-redis-iot-01
producer_commit: 1745074e5ad5a4bfae6741743f05db5ef32095f9
report_commit: 760cdf92f58e1762c235ae87c53d9e26217469a5
contract_version: 1.0.0
schema_revision: 2026-09-24-v1
candidate_format: DETACHED_V1
detached_candidate_approved: true
candidate_path: docs/l4desk/handoffs/L4D-REDIS-IOT-01-candidate.md
report_path: docs/l4desk/handoffs/L4D-REDIS-IOT-01-report.md
contract_kinds:
  - API
  - EVENT
  - DEPLOYMENT
consumers:
  - L4D-08A-MEDIA
next_prompt_id: L4D-08A-MEDIA
supersedes: []
status: CANDIDATE
artifact_paths:
  - app-service/core/config.py
  - app-service/core/diagnostics/sessions.py
  - app-service/core/redis_helper.py
  - app-service/core/remote_input/leases.py
  - app-service/core/remote_input/presence.py
  - app-service/create_api_app.py
  - app-service/tests/conftest.py
  - app-service/tests/core/test_l4d_redis_registries.py
  - compose.yaml
  - pyproject.toml
  - uv.lock
  - docs/l4desk/handoffs/L4D-REDIS-IOT-01-report.md
artifact_sha256:
  - 58767038f7029badc00c2f70a74897ac7352a0407207cbc7f78db9d9c2b1b9a8
  - 73b1c08583a88a062423bca087679e63ec4d9e76c0eaaa5e38f83791204d2103
  - fa689cdbc7efd67bac136b7cec033d01f33c925b1432d51561ef0c61b58e78ae
  - 2cc6b508583d184087be18177863b14dab15b467449009bb39d56153dc6bdb84
  - c7a25b2ed289c3985c28f185c07f91b16cbb1801ae014cdb0d0879d342606cc3
  - 526b81a01c0c459d5850305cfc3752ea4f3581989491acb6c02d9b30e28ad7ee
  - d9e3cf15b85c8f7fc9ae8473da92bc21910ee898742b4bf7547dbd637be2c2b7
  - cd87202af21410cfd0afc260303f3ae5e4cd5ee788642e1b5180ed77c78ffe0f
  - cd0bac4fd02948fca12b2574ab63671b75106ff68c6563cfa6d55e87e21bdedc
  - fbf4f878191ee7b3b7cc54453c8a8f3f9a271fbd78cf171915723e5b25f0c77b
  - 0905a26782a6398d88f9e93a07625f15745a83597815274820063fb9d2e45039
  - 4d9bfd8355ce921229f0348db9327b06e3727d8ec2aeedefa317cddd2e86ed03
contract_payload:
  architecture_sections: [3, 4, 5, 6, 8, 11, 12, 16, 17]
  registration_id: R-L4D-REDIS-IOT-01-v1
  redis_database: 0
  redis_key_prefixes:
    leases: "l4d:lease:<lease_id>"
    active_leases: "l4d:lease:active:<sn>"
    presence: "l4d:presence:<sn>"
    inventory: "l4d:inventory:<sn>"
    stream: "l4d:stream:<sn>"
    diagnostics: "l4d:diag:session:<session_id>"
  pubsub_channels:
    lease_revoked: "l4d:pubsub:lease_revoked"
  tests_passed: 415
  verification_status: VERIFIED_READY
```
<!-- HANDOFF:H-L4D-REDIS-IOT-01-v1:END -->
