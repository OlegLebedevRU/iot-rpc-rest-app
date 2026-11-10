# Python dependency maintenance —2026-11-10

User authorized all dependency upgrades inside existing version ranges and
coordinated local/builder/production maintenance. Source base master179872f.

- Lock refreshed by uv0.13.7 on Python3.14.10; explicit sqlalchemy[asyncio] retains
  greenlet required by SQLAlchemy2.1. Runtime base and uv images pinned by OCI digest.
- Resolved FastAPI0.162.4, SQLAlchemy2.1.8, asyncpg0.32.0, Pydantic2.14.3,
  cryptography50.0.2, FastStream0.7.8, aio-pika10.2.3 and Gunicorn27.0.0.
- Runtime-store adaptation only states the non-null type of PostgreSQL's clock
  result. No SQL, transaction cleanup, session/owner fences or MQTT client changes.
- Full local suite1215passed/13skipped. Critical runtime modules pass scoped
  Ruff/Black/Pyright; full-source Black273files unchanged. Broad repository Ruff
  scans report import/style findings in unchanged source; no mass rewrite included.
- OSV audit of resolved Linux dependencies reported zero advisories. This is a
  dependency database check, not complete application security certification.
- Shared test-generated contract files restored after confirming only line endings
  differed; protocol schemas and migration heads are unchanged.
- GitHub GHCR workflow explicitly disabled; source already had only manual dispatch.
  Release remains builder -> private registry -> production immutable digest.
- Accepted source master4c512cbe338cf4519c49fc52e16390b8b2afe014, PR162. Linux gates
  and registry publication completed after restoring the runner's Buildx selector
  ownership through the etranprocessing installer package; no direct hotpatch.
- Production app1 and dedicated runtime now use
  sha256:51fc538ba3798459814494e81d25ab06a1063d6cbe38c33d9a946652cd00bb7f.
  Verified Python3.14.10/uv0.13.7 and the new package versions in both containers.
- Five opt-in PostgreSQL18 serialization/rollback/recovery tests passed on builder.
  Isolated container, tmpfs and test credentials removed. Real managed-DB SELECT1
  using the new app1 image also passed before rollout; migration head unchanged.
- Complete Compose overrides/env/commands/volumes and20m/3 logging preserved.
  Operator explicitly authorized interruption of the active4623 stream. Following
  restart: generation35, queue0, no active old stream; owner and last_tick advance.
- app1 health200, RabbitMQ39queues/0ready/0unacked/53consumers, no ERROR/traceback
  in bounded post-release app/runtime logs. No other infrastructure recreated.
- Precise local .python-version now pins the already tested3.14.10; this follow-up
  changes developer interpreter selection/documentation only and needs no rebuild.
- User subsequently confirmed everything visually works after deployment. This is
  operator acceptance; no additional automated browser/decode test is claimed.
