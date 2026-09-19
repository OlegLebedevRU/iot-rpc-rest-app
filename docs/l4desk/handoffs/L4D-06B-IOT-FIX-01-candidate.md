<!-- HANDOFF:H-L4D-06B-IOT-FIX-01-v1:BEGIN -->
```yaml
handoff_id: H-L4D-06B-IOT-FIX-01-v1
prompt_id: L4D-06B-IOT-FIX-01
prompt_type: corrective-provider
target_repository: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
git_branch: l4desk/l4d-06b-iot-fix-01
producer_commit: 4a0f9d4b218e96273eed605e9edd0f9ab3564b68
report_commit: 2bca5e83ec9e4cf0c0774a3f4e1f7dcfb2bb0dfa
contract_version: 1.0.0
schema_revision: 2026-09-18-v1
candidate_format: DETACHED_V1
detached_candidate_approved: true
candidate_path: docs/l4desk/handoffs/L4D-06B-IOT-FIX-01-candidate.md
report_path: docs/l4desk/handoffs/L4D-06B-IOT-FIX-01-report.md
contract_kinds:
  - API
  - EVENT
  - DEPLOYMENT
consumers:
  - L4D-06B-IOT
next_prompt_id: L4D-06B-IOT
supersedes: []
status: ACCEPTED
artifact_paths:
  - docs/l4desk/contracts/schemas/device_provisioning_openapi.json
  - docs/l4desk/contracts/schemas/device_provision_request.schema.json
  - docs/l4desk/contracts/schemas/device_provision_response.schema.json
  - docs/l4desk/fixtures/device_provisioning_examples_v1.json
  - docs/l4desk/handoffs/L4D-06B-IOT-FIX-01-report.md
artifact_sha256:
  - dccc1beefc97be7b4d89502193cb865e95f7fe3b4a3bbae8d528574c7d736a3d
  - 3cba891ebef0e1783bda8bdf02821e3eb6f9a12eba080b31a735fb2c5a667081
  - 0f2914e286fbe665401dc412acb4308aa91741c5f6d3a141acd301e1bf1cf3a8
  - 86dd26818fadf2d8c4ea07113a77410f19f3cbbf64fb6eccc098100bf893c2fb
  - 5759fc1ab00dacfe2f16585f4df2753a8b4d5a8bc197af22f5b99c0fcff62d80
contract_payload:
  corrects_candidate: H-L4D-06B-IOT-v1
  architecture_sections: [3, 4, 5, 6, 11, 12, 14, 16, 17]
  registration_id: R-L4D-06B-IOT-FIX-01-v3
  service_key_header: X-Internal-Key
  endpoints:
    provision: /api/internal/v1/devices/provision
    get_by_operation: /api/internal/v1/devices/provision/by-operation/{operation_id}
    get_by_sn: /api/internal/v1/devices/provision/by-sn/{sn}
    get_by_operation_legacy: /api/internal/v1/devices/provision/{operation_id}
  durable_event_type: device_provisioned
  alembic_revision: 0005_device_provisioning
  tests_passed: 384
  verification_status: VERIFIED_READY
```
<!-- HANDOFF:H-L4D-06B-IOT-FIX-01-v1:END -->
