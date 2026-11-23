# CTL compact presence, revision 1

On dev/{SN}/ctl a participating agent sends its complete online presence at CONNECT and after a change to inventory, desktop availability, session, capabilities or stream state. Each new full publication has a new 16-character lowercase hex presence_rev. QoS 1, retained. Offline and Will use the existing offline contract. Legacy agents continue sending complete periodic presence.

At the existing presence interval the agent may send a QoS 1 non-retained heartbeat:
```json
{"v":1,"type":"heartbeat","presence_rev":"06c935681a748abc","seq":1}
```
Sequence increases within one revision. A duplicate or older sequence cannot refresh liveness. Only an online snapshot with the same revision in the topic SN's registry can be refreshed. Heartbeats do not assert media proof, capabilities, enrollment, or lease renewal. Ignore a stale heartbeat for liveness. If the full snapshot is missing or the revision mismatches, the consumer requests inventory_get at most once per SN per minute; the compact agent also republishes a complete retained presence on this command. Redis liveness TTL remains 90 seconds in the current deployment. The inventory embedded in the online snapshot remains available when the separate daily cache expires. Deploy the consumer before enabling compact agents.

Pilot agents use compact updates only when the stream is stopped. Active streams continue periodic complete snapshots.
