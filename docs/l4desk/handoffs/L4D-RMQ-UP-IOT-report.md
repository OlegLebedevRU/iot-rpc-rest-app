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
status: DEPLOYED
accepted_at_utc: '2026-09-29T13:11:18Z'
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
- `definitions.json` seeds service users and topology only; dynamic device users and ACL come from PostgreSQL. RabbitMQ must retain both its named volume and stable Erlang node name. The first production restart reused the volume but changed node name, exposing an empty Mnesia directory; app1 restored 114 active users and their ACL after its restart.
- Broker console and connection logs use `warning`; successful connection history remains available through application state and management API.

## Rollout and rollback

1. Record image IDs, volume name, non-secret topology names and counts; export live definitions to a protected backup.
2. Release the tested `app1` image, then update the versioned RabbitMQ config, seed definitions and Compose node identity via the standard repository deploy flow.
3. Restart only RabbitMQ, preserving its named volume. On the one-time node-name migration, restart app1 to reconcile ACL. Verify health, static topology, active user ACL and absence of blocked users. Verify a second restart retains those users without another app1 restart.
4. Roll back the app1 image and versioned broker files if health or access fails. Do not restore a live definitions export blindly: it can contain blocked users.

## Evidence

- Local test and lint results: `uv run pytest -q` 434 passed; changed-file `ruff check` and `black --check` passed; JSON seed parsed with two service users and zero device users.
- Production app1 image: `sha256:87691012cb6da155795372fd2fa627cb19673c2c7e91029b42eeab8974dd959c`, source `9513df6880a1c93c1c8e10673954c5a3d1efd257`.
- First broker restart with changing node name: two seed users only; app1 restart restored 114 active users, 114 exact topic ACL, 40 queues, 9 exchanges and all 14 static bindings; two blocked users remained absent.
- Terminal 1000009 preflight: online and service online after broker recovery; app1 `/docs`: 200.
- Runtime Compose was changed by exactly two lines (`hostname` and `RABBITMQ_NODENAME`) after explicit approval; the versioned source is `compose.yaml` in this repository. Production checkout is `c105eeeb2f1ee212f8b285d1fbc2d78c91122cf0`.
- One-time migration to `rabbit@rabbitmq` initially loaded two seed users, then app1 startup restored 114 active users, 114 device topic ACL and 228 vhost/topic permissions updates with zero errors. Two blocked users remained absent.
- Repeat RabbitMQ recreate retained `rabbit@rabbitmq`, the same `user1_rabbitmq_data` volume, 116 users and 114 device ACL **without restarting app1**. App1 start timestamp remained unchanged.
- Final RabbitMQ: healthy; 116 vhost permissions, 9 exchanges, 14/14 baseline static bindings, 41 queues (dynamic MQTT queues can change with connections). Terminal 1000009 online and `svc_online`; app1 `/docs` 200.
- The original live definitions export included four durable MQTT subscription bindings for one device that failed authentication after restart. They were not restored; all static bindings were restored. Do not import that export wholesale because it also contains accounts revoked during this release.
- An orphan RabbitMQ user with no PostgreSQL connection record and no active socket was deleted after separate operator approval.
