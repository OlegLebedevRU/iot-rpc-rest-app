# Internal video watch feed v1

The IoT provider exposes `WS /api/internal/v1/remote-input/ws/watch/{sn}` to
MenuBuilder. It requires the configured internal service key in the
`X-Internal-Service-Key` header and a positive tenant ID in `X-Org-Id`.
The provider checks that the tenant owns `sn` before accepting the socket.
Missing/invalid credentials or ownership close with code `4403` without a
snapshot. The key is never passed in a URL.

On connection, the provider subscribes to local presence and stream queues,
then sends one authoritative `snapshot` message:

```json
{"type":"snapshot","data":{"sn":"DEVICE_SN","agent":{"online":true,"desktop_available":true,"stale":false},"lease":{"active":false}}}
```

`data` is the existing internal REST `StatusResponse` JSON shape, with its
normal optional fields. Subsequent messages are hints to refresh that REST
snapshot, not state transitions:

```json
{"type":"invalidate","kind":"stream","online":null,"state":"stopped","reason":"ended","stream_instance_id":"UUID","timestamp":"UTC"}
{"type":"invalidate","kind":"presence","online":false,"state":null,"reason":null,"stream_instance_id":null,"timestamp":"UTC"}
```

The consumer must fetch the current snapshot after each invalidation and on
reconnect. It must never restore `running` from an old event or treat an event
from a prior `stream_instance_id` as the state of the current stream. The
`timestamp` is an observation time if the agent event omitted one. The feed
is read-only: any inbound text closes with `4403`; it never creates, renews,
releases, or alters a lease. Lease keepalive remains a separate flow.

The subscriptions are **process-local**. This contract is valid only while
`app1` has one worker (`WEB_CONCURRENCY=1`). Cross-worker fanout is deferred
until after the L4D cascade. Slow subscribers are closed after a send timeout
or a pending event backlog exceeding 100; the consumer reconnects and
re-reads the snapshot. Media quality and decoded frames are outside this IoT
feed. The existing lease control WebSocket and REST status API are unchanged.
