# Camera runtime recovery

The dedicated issuer uses its own one-connection PostgreSQL pool:5s connect,
command and pool waits. SQL waits, including locks, use the driver's5s command
budget; no server startup settings are sent because the managed proxy rejects
statement_timeout at startup. API pools retain
their existing configuration. Candidate discovery has a10s budget and each
per-device pump40s (including the existing bounded16-message outbox batch).
Failures retire local clock state before fenced reacquisition and retry with
1–5s backoff. A separate thread exits the issuer after60s without progress,
including wedged cancellation/transaction cleanup; Compose unless-stopped
restarts it. No expired stream is restarted or lease deadline extended.

Pending enrollment hellos for the same SN, boot and capability/revision context
are materialized in the existing bounded JSON inbox. Different enrollment IDs
may supersede pending jobs; their submit waiters receive camera_job_superseded.
Exact duplicates share the existing job/deadline. Expired jobs are retired before
capacity checking. High-water regression is rejected. Pending handshakes,
different boots, ACKs and control commands are not combined. Receive order is
only a candidate selection; existing challenge/epoch checks remain authority.

No schema migration, new broker or protocol change is required. During a DB
outage admission remains fail-closed; processing resumes after connectivity
returns. An ambiguous commit/delivery never authorizes an ad hoc START replay.

Validation: full app-service tests; focused timeout/watchdog/inbox tests. The
opt-in test_camera_db_recovery.py requires CAMERA_TEST_DB_URL pointing only to
a disposable PostgreSQL and verifies SQL timeout/backend disconnect recovery.
Never run fault injection against production.
