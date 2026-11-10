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
  findings predate this maintenance; no mass import/style rewrite included.
- OSV audit of resolved Linux dependencies reported zero advisories. This is a
  dependency database check, not complete application security certification.
- Shared test-generated contract files restored after confirming only line endings
  differed; protocol schemas and migration heads are unchanged.
- GitHub GHCR workflow explicitly disabled; source already had only manual dispatch.
  Release remains builder -> private registry -> production immutable digest.
- Linux build and deployment results will be recorded after the accepted release.
