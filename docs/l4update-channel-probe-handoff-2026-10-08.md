# L4Update IoT transport changes — 2026-10-08

## Intake and authorization

Owner: IoT transport. User accepted a separately marked orphan transport probe
and event76/tag449 infrastructure result without billing. Scoped external repo
work only; no deployment, REST calls, production connection, extra MQTT client or
MB/PB changes. Existing broker CN/topic authorization remains mandatory. Device
and active tenant binding are verified read-only, never from body identity.

## Implemented

- Early req/evt dispatch marker `iot_probe=1`, rejected marked input cannot enter
  task lifecycle, event collection, billing or webhooks.
- Exact v1 schemas, JSON duplicate rejection, integer version (no bool/float),
  bounded body/identity/rate/nonce/id fields. Fresh N/M correlation and EVA echo N.
- Local processing/publishing budget and reply expiry10s. Rate limits per worker
  64/SN/10s,128/s overall,4096 identities; no external registry/persistence.
  Ten sequential REQ+EVT barriers fit the per-device bound; the 65th message fails.
- Valid CN-scoped unknown identity/DB failure responds with generic status=error
  in the same exact RSP/EVA schema, never success or tenant/database details.
  Lookup has2s budget inside10s total; schema/rate rejection drops. Native
  `tools/l4con/src/link_probe.c` accepts error on both legs as ERROR_BAD_NET_RESP.
- Current capability polling allowlist adds7021/7023/7030–7033; retired7020/7022
  excluded. Generic TaskCreate addressed703x already works <=7099. Existing invalid
  capability fallback is unchanged; typed703x payload validation remains native.
- Event76/tag449 registered in docs; ordinary durable collector and EVA unchanged,
  new/duplicate76 payload preserved;76 and75 excluded from evt/activity billing.

## Evidence and remaining work

`uv run --locked pytest app-service/tests/core/services/test_channel_probe.py
app-service/tests/core/services/test_certificate_inventory_event.py
app-service/tests/core/services/test_device_tasks_select.py -q`:51 passed.
Changed Python files ruff check and black passed; git diff --check passed.
Full release gate `uv run --locked pytest -q app-service/tests`:575 passed,
7 skipped,4 warnings (15.64s), local mocked fixtures. Log under ignored
`.pytest_cache/l4update-release-readiness.log`. This is not production acceptance.
Tests mock publishers and readonly identity results; no live broker/channel or
PostgreSQL durability acceptance claim. Deployment and full integration remain.

Probe freshness/order is the client gate's responsibility; server is stateless
across workers and does not prove a prior N request existed. It verifies identity
independently for each leg. Downlevel peers fail timeout, not automatic fallback.
Transport probe does not prove durable event insertion/webhook readiness.

Four pre-existing modified files under docs/l4desk/contracts/schemas were left
unchanged by this task. No secret file was read or changed. No commit performed.

## Read-only production readiness audit

Container `app1` was inspected via approved SSH on2026-10-08. It is running image
`sha256:36fb27a6826927d1e27527d61a6c26a3a165c05a26882cd2e8d4bff99167387e`,
revision `6209faf870d9d05028255c9e92f30017a33be781`.
Read-only `/app/core` source-presence checks report:
orphan module absent, early `dispatch_probe` absent,7032 capability allowlist absent,
and75/76 non-billing exclusion absent. These accepted local changes are undeployed.
Therefore the mandatory new orphan barrier cannot be claimed ready against this
runtime. No live probe/RPC, database mutation, deploy or broker client was created.
The public API being reachable would not prove these MQTT handlers exist.

## Concrete clean release preparation

Fetched `origin/master` remains `2ffa1403b4529ae1260b14c662e23e9c43a858d6`.
Dedicated branch `l4update/channel-probe-result76-20261008` in sibling worktree
`D:\work\iot.leo4.ru\iot-rpc-rest-app-l4update-release` contains only these12task
files; four unrelated dirty schemas remain solely in the original checkout.
No model/Alembic delta exists between deployed6209faf and fetchedmaster for this
release baseline. Task itself adds no migrations/model changes.
Commit/PR accepted into master, immutableSHA build on the standardbuilder,
registry artifactdigest, then app1-onlyproductionpull and handlerpresence checks
remain. Do not copy source files into running container or build on production.
