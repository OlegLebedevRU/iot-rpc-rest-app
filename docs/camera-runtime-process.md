# Camera issuer process

The API and MQTT ingress workers enqueue camera jobs in the existing PostgreSQL
authority inbox and wait for durable results. They do not pump actors, allocate
issuer clocks, own camera authorities, or publish the camera outbox. The API's
normal Gunicorn `max_requests=1000`, jitter `100` remain unchanged.

One `python run_camera_runtime.py` process executes the existing per-SN actors.
It connects to the existing PostgreSQL, Redis and RabbitMQ and registers only
publishers. It never consumes the shared MQTT control queue: API consumers still
validate/enqueue camera input and handle desktop input. Consumer acknowledgement
continues to follow completion of the durable camera submission.

This separates HTTP worker recycling from camera issuer lifetime. It is not HA:
loss/restart of the dedicated process still invokes the existing owner expiry,
new generation/epoch and retirement. A new explicit START is required. Clock
origins remain process-local; no TTL, fencing, frozen schema or admission
semantics change. There is one process for all configured cameras, not one
process per camera. Existing serial bounded actors/inbox limits remain; capacity
for hundreds of cameras has not been established by this change.

## Deployment boundary

Build one accepted immutable image for both app1 and camera-runtime. Complete
the normal app migration once before starting the worker; the worker entrypoint
bypasses `prestart.sh` and does not run migrations. The optional Compose
`camera-runtime` profile has no published ports or HTTP healthcheck. Existing
camera runtime gate must be enabled; a mistakenly launched disabled worker fails
visibly instead of acquiring authorities.

For production, preserve every effective Compose overlay and app1's private
environment/certificate/network configuration. Explicitly give the new worker
that same resolved configuration, the candidate digest, its dedicated entrypoint,
no ports, and a separate log mount. Do not copy app1's HTTP healthcheck, container
name, or command. Do not recreate infrastructure. Confirm no active camera lease
before transition; verify publisher-only registration, both roles, image hashes,
scoped allowlist and writers disabled. Keep app1 rollback and worker removal as
one coordinated rollback: old app1 again owns actors. Real issuer replacement
still retires old attempts; never claim seamless issuer restart.

## Reliability follow-up

The coordinated work plan is
`D:/.codex/siplite-hevc/tasks/MONOTONIC-RELIABILITY-SCALING.md`.
It covers separating durable issuer authority from executor fencing, verified
clock domains/recovery, HA, sharding/fairness, database load and acceptance at
100 then 500 cameras. These are follow-up tasks, not implemented guarantees.
