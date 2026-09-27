# 18C detached candidate

Pending independent controller acceptance. This file is not the cascade journal.

<!-- HANDOFF:H-L4D-18C-IOT-v1:BEGIN -->
```yaml
handoff_id: H-L4D-18C-IOT-v1
status: ACCEPTED
contract_kinds: [DEPLOYMENT, REPORT]
producer_prompt_id: L4D-18C-IOT-FIX-01
producer_scope_project: iot-rpc-rest-app
producer_report_path: docs/l4desk/handoffs/L4D-18C-IOT-FIX-01-report.md
producer_branch: l4desk/l4d-18c-iot
producer_commit: 35f1fce054e388a2206af45f1416b9572b0614a9
report_commit: fa7a91a631ced5134104e8bef61a69aa620c26a3
contract_version: 1.0.0
schema_revision: 0008_org_reservations
artifact_version: 0.1.1
candidate_format: DETACHED_V1
detached_candidate_approved: true
candidate_path: docs/l4desk/handoffs/L4D-18C-IOT-FIX-01-candidate.md
artifact_paths:
  - docs/l4desk/handoffs/L4D-18C-IOT-FIX-01-report.md
  - docs/l4desk/handoffs/evidence/18c-rollout/18c-production-archive.json
  - docs/l4desk/handoffs/evidence/18c-rollout/18c-production-final-smoke.json
  - docs/l4desk/handoffs/evidence/18c-rollout/18c-production-image-final.json
  - docs/l4desk/handoffs/evidence/18c-rollout/18c-production-lock.json
  - docs/l4desk/handoffs/evidence/18c-rollout/18c-production-provider.json
  - docs/l4desk/handoffs/evidence/18c-rollout/18c-production-runtime-final.json
  - docs/l4desk/handoffs/evidence/18c-rollout/agent-provider-vectors.txt
  - docs/l4desk/handoffs/evidence/18c-rollout/backup.json
  - docs/l4desk/handoffs/evidence/18c-rollout/linux-functional.txt
  - docker-files/app-service/Dockerfile
  - .dockerignore
  - l4desk-service/docs/prompts/contracts/archive-manifest-v1/archive-manifest.schema.json
  - l4desk-service/docs/prompts/contracts/archive-manifest-v1/examples.json
artifact_sha256:
  - 7f8fd3a4b312f75bc70e7bdeea236baae14420331e78d173d2a042f77ae18dc5
  - 8183ac58ca7035ef20b91b12f1017fde6f7ff38df0b39b42a4c4ced8f0791600
  - 042f54ea307fa124bd37f0a87a3ba322fcbd558a7d75bbc49bb7f3c1b5676823
  - 28a17171da2ee28087574ffffe5f6962c86a451e1f8d8ad7eb91663ba4020660
  - e8ea14bdbf46f5e0dbd64393af62403a1734d3ebd5e1da0a02329b4c127d7bbe
  - 83f727504e52336312cf868ef05adcd00faa5f0d5dbb52b22f2c1a1337050f72
  - 9e9e6f6a7e12fd008d3fc47014e14f5bcbc899f2b5b4e8c2692cb657b574e4c1
  - c339da045853755ab455bffa7518820094d25bf0e3e0ed6e7f349ad35c6d536f
  - e4b96a83cf6c289b256d615c49780e451124395c947adc82ff20118d32f2a626
  - 53ed660abb3f0825e595fcbe341beb10a0cbaca33339659b11df8c967f7f600e
  - a6ced58212fe6b68ba606b28f634ddf4ae07c8d084e128791352bdeb3685b0d7
  - 6859795222e48b10c76288aebf957f5541adf1d559824a345516e6af434e6b5a
  - 3a908c6fe80177126ba783fbf70c3c0de76b8428b3d8fd8a135e08cbd347bfc2
  - 29379c6f4559992f86f48ef194379814228c8e653155af64e219c8c5c686a717
artifact_commits:
  "docs/l4desk/handoffs/L4D-18C-IOT-FIX-01-report.md": fa7a91a631ced5134104e8bef61a69aa620c26a3
  "docs/l4desk/handoffs/evidence/18c-rollout/18c-production-archive.json": fa7a91a631ced5134104e8bef61a69aa620c26a3
  "docs/l4desk/handoffs/evidence/18c-rollout/18c-production-final-smoke.json": fa7a91a631ced5134104e8bef61a69aa620c26a3
  "docs/l4desk/handoffs/evidence/18c-rollout/18c-production-image-final.json": fa7a91a631ced5134104e8bef61a69aa620c26a3
  "docs/l4desk/handoffs/evidence/18c-rollout/18c-production-lock.json": fa7a91a631ced5134104e8bef61a69aa620c26a3
  "docs/l4desk/handoffs/evidence/18c-rollout/18c-production-provider.json": fa7a91a631ced5134104e8bef61a69aa620c26a3
  "docs/l4desk/handoffs/evidence/18c-rollout/18c-production-runtime-final.json": fa7a91a631ced5134104e8bef61a69aa620c26a3
  "docs/l4desk/handoffs/evidence/18c-rollout/agent-provider-vectors.txt": fa7a91a631ced5134104e8bef61a69aa620c26a3
  "docs/l4desk/handoffs/evidence/18c-rollout/backup.json": fa7a91a631ced5134104e8bef61a69aa620c26a3
  "docs/l4desk/handoffs/evidence/18c-rollout/linux-functional.txt": fa7a91a631ced5134104e8bef61a69aa620c26a3
  "docker-files/app-service/Dockerfile": 35f1fce054e388a2206af45f1416b9572b0614a9
  ".dockerignore": 35f1fce054e388a2206af45f1416b9572b0614a9
  "l4desk-service/docs/prompts/contracts/archive-manifest-v1/archive-manifest.schema.json": 35f1fce054e388a2206af45f1416b9572b0614a9
  "l4desk-service/docs/prompts/contracts/archive-manifest-v1/examples.json": 35f1fce054e388a2206af45f1416b9572b0614a9
compatibility:
  backward_compatible_with: [H-L4D-18C-IOT-EVIDENCE-CONTRACT-01-v1]
  breaking_changes: false
  notes: Existing MQTT, provider APIs, event feed and Agent 1.8.2-beta-1 remain compatible.
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  archive_enabled: false
contract_payload:
  registration_id: R-L4D-18C-IOT-FIX-01-v1
  required_inputs: [H-L4D-18B-PB-v1, H-L4D-18C-IOT-EVIDENCE-CONTRACT-01-v1]
  source_archive_sha256: 6401058dc075164d660aaf38c686c05939e6737a9f7ba59f685ad7992781081e
  production_image: sha256:d2540c3e7c5da54077a0543491a6b0bb0782244c9837d7430b218bbf730568ba
  image_tag: user1-app1
  alembic_head: 0008_org_reservations
  migration_action: already_at_head_no_ddl
  image_source_files_matched: 207
  private_payload_files: 0
  runtime_settings_equal: 12
  accepted_agent_baseline: 1.8.2-beta-1
  rollback_image: sha256:29aa88169ab8b051705044f0feb1ad8b4d5af5827bcef5294b437c7e29b9c431
  rollback_status: READY_NOT_EXECUTED
  backup_sha256: 749bcf6245566b2b022b4000ce322feb1c7d4b9b6fb411c13307d1f07406bb01
  checks:
    local_suite: 431_passed
    final_linux_functional: 24_passed
    older_agent_provider_vectors: 15_passed_9_historical_digest_cases_replaced_by_packet_gate
    current_agent_browser: operator_attested_start_motion_stop
    feed_resume: HTTP_200_strict_cursor_repeat_stable
    session_lock: HTTP_409_session_busy
    stop_replay: HTTP_200_same_closed_at
    archive: synthetic_nonempty_dry_run_rollback_reread_checksum
    queues_ready_unacknowledged: [0, 0]
    duplicates_orphans: [0, 0]
supersedes: []
known_risks:
  - Archive worker disabled; empty months reject empty record_types under current schema.
  - Dry-run verification was independently checked; production purge and storage retention not exercised.
  - Two requested sessions predating deployment remain unchanged.
  - Old Agent checks are provider contracts; physical old-terminal enrollment was not repeated.
  - Rollback image and backup verified; production rollback not executed.
  - Existing deprecation warnings retained.
consumers: [L4D-18D-MEDIA, L4D-18E-MB]
next_prompt_id: L4D-18D-MEDIA
```
<!-- HANDOFF:H-L4D-18C-IOT-v1:END -->
