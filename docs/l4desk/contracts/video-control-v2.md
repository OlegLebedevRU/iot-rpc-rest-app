# IoT negotiated video control

Contract revision: `hevc-contract/2.0.0`, frozen digest
`f065b967cd10c2c709fb394ef9e6c2ecf74f77de060d88c9a821cc9069766ac4`.
Normative CTL definitions and examples: [G0 package](../../../contracts/hevc-v2/README.md).
[OpenAPI snapshot](video-control-v2.openapi.json) is generated from the real internal
router by `uv run python deploy/export_video_openapi.py`. Internal routes remain
hidden from the public OpenAPI. The runtime schema is an exact copy of G0,
checked by a regression test. No independently renamed wire fields.

## Configuration and routes

Both flags default to false:

* `APP_CONFIG__REMOTE_INPUT__VIDEO_V2_ENABLED` enables negotiated CTL v2 starts.
* `APP_CONFIG__REMOTE_INPUT__VIDEO_HEVC_CHAIN_READY` additionally allows HEVC.
  Set it only after TASK-40 verifies the actual server chain. This flag is a
  server operator assertion, never accepted as a client request field.

A separate `APP_CONFIG__REMOTE_INPUT__VIDEO_TEST_CAMERA_SNS` allowlist (empty by
 default) permits only explicitly provisioned test SNs with a `usb-camera`
 descriptor whose source ID starts with `test-`, and a live `camera` backend
 capability. Hardware remains false for this RTSP passthrough. This exception
 establishes server transport readiness only; desktop hardware readiness still
 requires the global chain flag and the hardware Media Foundation probe.

`VideoStateView` carries the stored START's `sn`, `lease_id`, `agent_instance_id`,
`operation_id` and `command_id` alongside `stream_instance_id`. The HTTP projection
sets `confirmation: "agent_ready"` only for a running record whose exact READY
has persisted an actual descriptor. It does not change the frozen CTL schema.

Base path: `/api/internal/v1/remote-input`. Existing internal service authentication,
tenant header, trusted caller user/session headers and the one active lease/SN
admission remain in force. V2 rejects missing user/session identity, except for
the existing explicit superuser path. A view lease cannot start a publisher.

| Method/path | Request | Result |
|---|---|---|
| GET `/devices/{sn}/video-capabilities?refresh=true` | Existing service/tenant auth; no lease required | `negotiated_v2`, nullable `video_capabilities` |
| POST `/lease/{lease_id}/stream/start` | Unchanged v1 `{mode,source_id,profile}` or complete `$defs.start` v2 | Unchanged v1 response or `VideoStateView` |
| GET `/lease/{lease_id}/video-state` | Lease tenant/owner/session | Full codec, immutable descriptor, actual descriptor, structured error and terminal reason |
| POST `/lease/{lease_id}/video-stop` | Complete `$defs.stop`, including all epoch identifiers | Idempotent terminal state; stale epoch is conflict |
| POST `/lease/{lease_id}/stream/stop` | Unchanged empty legacy request | Existing owner stops current publisher using its actual CTL version |

The explicit `v:2` request includes `codec_policy`, concrete `resolved_codec`,
delivery, lease deadline, operation/stream IDs and descriptor. BFF must first
authorize/choose parameters and prepare the l4media route using exactly that
descriptor. IoT does not create Janus routes. Use the G0 fixture payloads as v2
request examples, replacing synthetic IDs and timestamps with live values:
[START](../../../contracts/hevc-v2/fixtures/hevc_start.json),
[H.264 v2](../../../contracts/hevc-v2/fixtures/h264_v2_start.json),
[STOP](../../../contracts/hevc-v2/fixtures/stop.json).

Legacy example remains:

```json
{"mode":"desktop","source_id":"display-0","profile":"low"}
```

Legacy response has only `stream_instance_id`, `result`, `state`, including
the prior optional/null rules. No descriptor/error/new nulls are appended.
An incompatible live source/profile now returns the existing-style HTTP409
`stream_conflict`; owner must stop it before creating another publisher.

## Capability, state and cleanup

V1 `capabilities:["video_contract_v2"]` only permits a read-only v2 query.
Neither EXE version nor retained presence grants HEVC. A v2 inventory ACK must
match a live random command ID and SN, arrive within the 5-second query, carry
a probe performed no earlier than that query, and have a positive remaining
validity no longer than60seconds. Queries have30seconds cooldown. Unsolicited,
duplicate, expired and pre-query cached results cannot negotiate capability.
Offline, session/screen/inventory/version/capability changes invalidate it.
Each enabled server worker startup rotates a shared Redis negotiation generation.
All workers consult that generation transactionally, so cached readiness from a
previous startup cannot authorize a new stream. A rolling restart may require a
fresh query after the cooldown; existing stream events and drain remain available.


PREPARE resolves Auto before descriptor commit. Unknown/stale/unready agent or
server means H.264. IoT never executes a candidate HEVC descriptor as H.264;
a different resolver outcome returns `codec_mismatch`. BFF must prepare a new
concrete H.264 descriptor, or use the legacy H.264 request for an older agent.
Explicit HEVC gets stale/unsupported/conflict before START. Exact encoded-sequence
probe track/profile/source/geometry and interactive-session binding are checked.
The current Windows desktop HEVC release requires hardware Media Foundation.

Redis `l4d:video:v2:{SN}` holds versioned full START, owner identities, actual
descriptor and terminal error. Stream/operation tombstones prevent reuse during
the record retention window. WATCH transactions serialize reservations and legacy
starts; incompatible publishers cannot replace a live epoch. Redis lease hashes
add only `stream_profile` and `stream_contract_version`, defaulting to v1 for old
records. Stream updates use compare-and-set and preserve the authoritative lease
deadline. Records live through that deadline plus300seconds (minimum300).
Capabilities are never usable beyond their own ≤60second validity, even while
the containing record remains for terminal diagnostics.

ACK accepted means starting; only exact READY means agent_ready. Neither proves
RTP or a browser decoded frame. Runtime HEVC failure is terminal; full wire error
is retained, HEVC becomes temporarily_unavailable, and no restart/fallback is
scheduled. Timeout/mismatch/publication failure records a producer-domain error
with unknown backend/stage rather than inventing a GPU diagnosis. Cleanup sends
a bounded epoch-specific STOP. If publication fails, the original terminal reason
is preserved and the producer's authoritative deadline is the final watchdog.
STOP records server intent; it is not evidence of physical process exit.

V2 stream notifications invalidate every subscribed authorized session through
the existing queues plus Redis pub/sub between workers. Consumers fetch the full
state after invalidation. Wire v1/WS event shapes remain unchanged. HEVC descriptor
records never enter legacy `l4d:stream:*` or the software inventory event75 path.
Old-epoch terminal/READY/STOP cannot mutate the new publisher. A duplicate terminal
event preserves the first reason. Keepalive sends v2 lease_renew with actual epoch
identifiers, reports server_accepted, and does not invent a terminal renewal ACK
that is absent from G0. No SQL migration or etran ORM change is needed.

## Admission boundary and TASK-30/40

Watcher leave only unsubscribes its own read-only notifications/PeerConnection.
It cannot acquire another user's publisher/input lease or use its owner/session
identity. Existing one active lease/SN remains unchanged. MenuBuilder TASK-30 must
bind all notifications to the real stream UUID and use video-state after an
invalidation; independent viewer leases remain a separate follow-up:
[viewer admission task](../handoffs/hevc-viewer-admission-follow-up.md).
Three subscriptions under the currently authorized owner prove media fan-out,
not admission of three independent users. TASK-40 owns live Janus/BFF/decode and
rollback/drain verification; unit tests do not establish deployed readiness.

## Drain and rollback

1. Disable new v2 starts. Preserve v2 readers, STOP and current-epoch events while draining.
2. Stop each live v2 publisher using its own lease/stream/agent/descriptor IDs;
   wait for route cleanup and producer exit or its deadline. No auto restart.
3. Save terminal v2 records for diagnosis, then remove only drained
   `l4d:video:v2:*` documents/tombstones and their negotiation cache. Do not clear
   another lease/tenant or the event75/certificate/billing/EVA paths.
4. Remove/drain v2 lease stream markers before deploying an old reader; retain
   terminal diagnostics separately. Restore the previous image by immutable
   digest using the app1 runbook. Existing legacy H.264 records stay in their
   original namespace and retain their protocol shapes.

No production deployment, registry publication, driver test or hardware readiness
is performed by TASK-10's local implementation checks.
