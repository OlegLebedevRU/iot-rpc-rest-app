# L4D IoT cascade: RabbitMQ access and remote shortcuts

## Task intake

- Goal: reduce RabbitMQ reconnect noise and make Alt+F4 and Win+D available to every authorized remote input lease.
- Owner: `app1` owns device state, provisioning and MQTT users; RabbitMQ owns transport and ACL enforcement. No database migration.
- Flow: device certificate CN → RabbitMQ user and topic ACL → `app1` device status; browser → `app1` lease policy → `l4desk` input command.
- Invariants: blocked devices never regain RabbitMQ access through recovery; one device cannot publish or subscribe under another SN; app1 input lease and agent capability checks remain required.
- Validation: Python tests, RabbitMQ configuration check, production definitions/ACL comparison and one terminal reconnect after the planned broker restart.

## Contract delta

```yaml
handoff_id: H-L4D-RMQ-UP-IOT-v1
status: READY_FOR_DEPLOY
contract_kinds: [MQTT_ACL, DEPLOYMENT, REMOTE_INPUT_POLICY]
producer_scope_project: iot-rpc-rest-app
producer_report_path: docs/l4desk/handoffs/L4D-RMQ-UP-IOT-report.md
breaking_changes: false
database_migration: none
```

- `alt_f4` and `win_d` are permitted by the app1 policy for any valid remote input lease. F12 keeps its separate gate. An older agent without quick-action support can still reject the command.
- Blocked device users are deleted from RabbitMQ, closing their connections. Startup and manual ACL reconciliation delete blocked users before restoring active ones.
- Device topic ACL remains mandatory. Its `{username}` expansion confines publishing to `dev.<SN>.*` and subscribing to `srv.<SN>.*`.
- Provisioning remains incremental for the submitted SNs. Startup and explicit admin recovery perform the full scan.
- `definitions.json` seeds service users and topology only; dynamic device users and ACL come from PostgreSQL. A normal restart preserves the named RabbitMQ volume.
- Broker console and connection logs use `warning`; successful connection history remains available through application state and management API.

## Rollout and rollback

1. Record image IDs, volume name, non-secret topology names and counts; export live definitions to a protected backup.
2. Release the tested `app1` image, then update the versioned RabbitMQ config and seed definitions via the standard repository deploy flow.
3. Restart only RabbitMQ, preserving its named volume. Verify health, static topology, active user ACL and absence of blocked users.
4. Roll back the app1 image and versioned broker files if health or access fails. Do not restore a live definitions export blindly: it can contain blocked users.

## Evidence

- Local test and lint results: `uv run pytest -q` 434 passed; changed-file `ruff check` and `black --check` passed; JSON seed parsed with two service users and zero device users.
- Broker restart and ACL restoration: pending production verification.
- Operator remote input check: pending after deployment.
