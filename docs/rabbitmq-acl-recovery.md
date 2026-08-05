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
2. `app-service` reads all device client IDs from the DB.
3. For every device it idempotently upserts:
   - RabbitMQ user;
   - vhost permissions;
   - topic permissions for `amq.topic`.
4. A PostgreSQL advisory lock prevents concurrent sync storms when multiple gunicorn workers start.

The manual admin action remains available for forced recovery:

```powershell
Invoke-RestMethod -Method Post "https://dev.leo4.ru/api/v1/admin/?action=get_u"
```

Use dry-run first when diagnosing:

```powershell
Invoke-RestMethod -Method Post "https://dev.leo4.ru/api/v1/admin/?action=get_u&dry_run=true"
```

## Operational rules

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
Invoke-RestMethod -Method Post "https://dev.leo4.ru/api/v1/admin/?action=get_u"
```

4. Watch RabbitMQ logs for remaining authentication errors.
5. If errors continue for specific serial numbers, verify their certificates and that CN/client identity matches the registered device SN.

## Notes

`rmq/definitions.json` is only a seed for base broker topology and bootstrap users. It must not be treated as the canonical storage for dynamic device ACL. Dynamic device ACL is derived from PostgreSQL and re-applied by `app-service`.

