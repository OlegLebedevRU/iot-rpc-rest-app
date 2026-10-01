# Event75: consolidation against current l4con contract

## Scope and contract

User authorized integrating IoT75 into master after l4media, before MenuBuilder.
Base origin/master3e6f997. No deployment, native client or database migration.
Source documents: current terminal event75 inventory contract and IoT MQTT
event/property/correlation specifications. Old candidate320ceac assumed MQTT3;
current l4con uses MQTT5 User Properties, so its general JSON fallback decoder
and older queue/result handler replacement were not copied.

| Flow | Contract | Delivery / duplicate | Error / compatibility |
|---|---|---|---|
| l4con → RabbitMQ → IoT | dev/{SN}/evt, MQTT5 metadata + JSON101/102/200/300 | QoS1, no retain; ordinary event dedup | current header metadata parser retained |
| IoT collector → storage/webhook/EVA | event75, tags324/440–445 | original payload; webhook only for new row; EVA for new/duplicate | ordinary collector and tenant binding retained |
| EVT subscriber → billing | code75 → no counter | no evt/activity publication | other codes, including900–999, unchanged |

Inventory444 remains a JSON array; package445 is string/null and distinct
from each file's PE version. Payload SN is descriptive, never the auth source.
The current client performs local certificate identity checks before publishing;
the server does not treat inventory as proof of application health or CA issuance.

## Implementation and validation

Billing helper returns None for75; subscriber then runs the ordinary collector
without the billing publisher. Synthetic tests verify unchanged original nested
payload, routing SN lookup, new/duplicate webhook behavior, EVA correlation,
and unaffected999/gauge billing. No test credentials are stored in this change.

Quality checks of changed subscriber revealed existing missing-correlation type
errors: REQ/RES now reject a missing UUID before task processing/billing, consistent
with the mandatory RPC correlation contract; regression tests cover both refusals.
Silent generic parser catches were replaced with specific catches/debug logging;
intentional nonfatal billing/optional RES relay catches are documented locally.

Python3.14: full pytest463 passed/7 skipped. Six PostgreSQL history tests need an
explicit localhost test DSN; the other skip is existing optional coverage.
Ruff/check/format and Pyright of changed source passed. No production/E2E rerun.
Schema fixture statuses produced by full tests contain no content diff and are
excluded from this commit. Historical candidates and their immutable SHAs remain
unaltered; this is an updated integration, not a claim that320ceac was merged.

Deployment, if later authorized: standard app1 builder→registry→pull by digest;
no schema migration or consumer roll is required for this billing exception.
