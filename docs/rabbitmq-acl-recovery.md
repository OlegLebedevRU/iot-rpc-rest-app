# RabbitMQ definitions and MQTT ACL recovery

## Problem

RabbitMQ stores runtime definitions, MQTT users, permissions and topic permissions in its data directory (`/var/lib/rabbitmq`). In this project that directory is mounted as the Docker named volume `rabbitmq_data`.

If the volume is removed, replaced by a different Compose project name, or RabbitMQ starts from an empty data directory, device MQTT users/ACL can disappear. The visible symptom is MQTT authentication failures such as:

- `MQTT connection failed: access refused for user ... invalid credentials`
- `Rejected MQTT connection ... Connect Reason Code 134`

Historically the recovery was manual via:

```text
POST /api/v1/admin/?action=get_u
```

## Current protection

The application reconciles RabbitMQ MQTT device access at startup:

1. PostgreSQL is the source of truth for registered devices.
2. `app-service` reads active and blocked device client IDs from the DB.
3. Blocked device users are deleted from RabbitMQ. RabbitMQ closes their open connections.
4. For every active device it idempotently upserts:
   - RabbitMQ user;
   - vhost permissions;
   - topic permissions for `amq.topic`.
5. A PostgreSQL advisory lock prevents concurrent sync storms when multiple gunicorn workers start.

Normal provisioning updates only the requested SNs. The full scan runs on app startup
or via the explicit admin recovery action. A RabbitMQ restart preserves dynamic
users and ACLs only when both the named volume and Erlang node name stay the same.
Compose pins `hostname: rabbitmq` and `RABBITMQ_NODENAME: rabbit@rabbitmq`.
A fresh broker needs both the static seed definitions and an app startup or
explicit reconciliation to restore active devices.
Never restore a blocked device from a saved live definitions export.

The manual admin action remains available for forced recovery:

```powershell
# Через внутренний шлюз или curl из контейнера app1:
Invoke-RestMethod -Method Post "https://dev.leo4.ru:3000/api/internal/v1/admin/?action=get_u" -Headers @{"X-Internal-Service-Key"="<INTERNAL_SERVICE_KEY>"}
```

Use dry-run first when diagnosing:

```powershell
Invoke-RestMethod -Method Post "https://dev.leo4.ru:3000/api/internal/v1/admin/?action=get_u&dry_run=true" -Headers @{"X-Internal-Service-Key"="<INTERNAL_SERVICE_KEY>"}
```

Или напрямую из контейнера `app1` на сервере:
```bash
sudo docker exec app1 curl -s -X POST "http://127.0.0.1:8000/api/internal/v1/admin/?action=get_u" -H "X-Internal-Service-Key: <INTERNAL_SERVICE_KEY>"
```

## Operational rules

For end-to-end safe infrastructure and RabbitMQ deployment procedures, refer to:
- [`manual-infra-and-rmq-deploy-runbook.md`](manual-infra-and-rmq-deploy-runbook.md) — complete runbook for deploying RabbitMQ configuration, definitions, and inter-service networks without data loss.

Do **not** run destructive Compose commands against production volumes:

```powershell
# Forbidden on production unless a tested backup/restore plan exists
docker compose down -v
docker volume rm <project>_rabbitmq_data
```

Keep the Compose project name stable on the server. A different project name creates a different named volume and RabbitMQ will look empty even if the old volume still exists.

Recommended deployment commands:

```powershell
git pull --ff-only
$env:IMAGE_TAG = "sha-<git-sha>"
docker compose pull app1
docker compose up -d app1
```

If RabbitMQ itself must be recreated, do not remove volumes:

```powershell
docker compose up -d --no-deps rabbitmq
```

## Checks after deployment or RabbitMQ restart

Before a planned restart, record the RabbitMQ container image ID, named volume,
and counts of users, vhost permissions, topic permissions, queues, exchanges and
bindings. Export live definitions to a protected backup, but do not import that
export after this release: it may contain blocked device users. Keep the named
volume attached. Deploy the checked `app1` image first so it can reconcile the
new ACL shape; then restart only RabbitMQ with its updated bind-mounted config.

After RabbitMQ reports healthy, compare the same counts and the non-secret names
of static topology objects. Verify that every active device has its user, vhost
permissions and topic ACL, that blocked device users are absent, and that one
known terminal reconnects and can publish/subscribe only under its own SN.
`definitions.skip_if_unchanged` can skip a repeated seed import; persisted Mnesia
is the primary recovery source only when RabbitMQ opens the same node directory.
The Docker container name alone does not pin the Erlang node name. If the volume is empty,
the seed restores service definitions and a fresh `app1` startup (or explicit
admin reconciliation) restores active device users and ACLs.

```powershell
# Container status
docker compose ps rabbitmq app1

# RabbitMQ volume mapping
docker inspect rabbitmq --format '{{range .Mounts}}{{println .Name .Destination}}{{end}}'

# RabbitMQ auth errors
docker compose logs --since 30m rabbitmq | Select-String "Reason Code 134|invalid credentials"

# App startup ACL sync log
docker compose logs --since 30m app1 | Select-String "RabbitMQ device ACL sync"
```

Expected app log after startup:

```text
RabbitMQ device ACL sync completed: {...}
```

## Emergency recovery

1. Confirm DB is available and contains devices.
2. Confirm RabbitMQ management API is available from `app1`.
3. Trigger the idempotent reconciliation manually:

```powershell
Invoke-RestMethod -Method Post "https://dev.leo4.ru:3000/api/internal/v1/admin/?action=get_u" -Headers @{"X-Internal-Service-Key"="<INTERNAL_SERVICE_KEY>"}
```

4. Watch RabbitMQ logs for remaining authentication errors.
5. If errors continue for specific serial numbers, verify their certificates and that CN/client identity matches the registered device SN.

## Notes

`rmq/definitions.json` is only a seed for base broker topology and service users.
It contains no device account. Dynamic device ACL is derived from PostgreSQL and
re-applied by `app-service`. Device topic permissions must restrict `dev.<SN>.*`
publishing and `srv.<SN>.*` subscriptions; omitting topic permissions grants access
to other devices' topics under the default RabbitMQ authorization backend.
