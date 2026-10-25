# Camera media-v3 runtime candidate

This candidate ports the durable camera runtime from IoT141/143 onto current
masterf54e7db without changing the already deployed desktop media-v3 pipeline.
It implements a new explicitly selected camera-v3 path, not production approval.
No deployment, gate, writer, allowlist or firmware installation is included.

## Exact independent revisions

Camera RPC/local configuration remains `siplite-camera/1.0.0`, main_app MQTT,
existing methods/topics and RES/gauge84 without new event types.

BFF -> IoT camera media/admission requests require the complete bundle:

```
X-L4-Media-Contract: l4-media/3.0.0
X-L4-Camera-Contract: siplite-camera/1.2.0
X-L4-Camera-Cadence: camera-cadence/0.1.0-proposed
X-L4-Camera-Enrollment: camera-enrollment/0.3.0-proposed
X-L4-Camera-Admission: camera-ctl-monotonic/0.2.0-proposed
```

Unknown, partial and mixed bundles reject before effects. Desktop HTTP remains
selected by its media header alone. Camera media requests never fall through to
Windows/desktop CTL2. Media-bound HTTP sends only X-L4-Media-Contract and service
authentication; camera markers stop at the BFF/IoT control boundary.

Common frozen media schema SHA256:
`b86ca6f066fcdecb09cf7145a7fb23d87b77311a53c7ea04f0fb6e8a905b2818`.
Owner observation1.2 schema SHA256:
`cba222ccdc2e10c446dc99e1bb0e2338d4fc08c28220f3bc02e8a8d391789194`,
imported byte-for-byte from MBa115c48b5420714cf66ce10e06974dfb221f4581.
New enrollment0.3 schema SHA256:
`e75ad9591d77a0c3b5703857cb9db7cf38131cd0781cbd19c57a0bfa322b98d3`.
Unchanged admission0.2 schema SHA256:
`e75e1c7f49f0d0fc68f6720a3c47766ccb4caad83d721b5d1b8aabe3d3b58a0d`.
Frozen enrollment0.1/0.2, camera1.0/1.1 and common media3 schemas are unchanged.
The new revisions retain proposal status until coordinated acceptance.

## Objects and control ownership

Capabilities returns contract_version3/media_contract_revision plus camera1.2
metadata, camera_observation and camera_capabilities. A strict observation has a
concrete common track, separate geometry generation and policy capabilities.
Its packet stays in gauge84 media_observations. It is never promoted to the
legacy camera.actual_track or treated as enrollment/readiness/forwarding authority.
The v3 view uses an at-most30s server-receipt freshness window and still requires
main_app, existing START SN/writer gates, native_auto and monotonic runtime gates.

Prepare body is exactly descriptor + physical_camera_mac. The descriptor uses
only the frozen common3 object, including contract_version3 and low/default;
there are no embedded camera/cadence/epoch properties. Source must be camera,
track/source/geometry must equal the fresh observation and the profile must be
advertised by the actual source. A MAC must be freshly authenticated on port2.
Both quality IDs may use one unchanged native format; neither forces encoder
resizing or rewrites size="",fps=0,bitrate=0 or original RTP timestamps.

New enrollment0.3 keeps the complete-offer0.2 actor/floor rules, changes only the
explicit media/observation selection and validates descriptor through the frozen
common external schema. HELLO advertises media_contract_revisions. OFFER, PROOF
and COMMIT carry media_contract_revision beside camera/cadence markers. See the
new packet for exact fields, canonical bytes and hashes. Existing durable JSON
version2 and migration0013 preserve floors, retired boots and owner fences.
No row loss/default reconstruction or issuer takeover resets the admission floor.

START/RENEW/STOP remain the frozen camera CTLv1 admission0.2 grammar and R/I
mapping. START mode usb-camera/profile default are historical camera adapter
tokens, independent of common descriptor quality low/default; its complete hash
binds the actual chosen policy. No desktop START or capability binding is sent.
Delayed/duplicate commands cannot restart the original monotonic lifetime.

Preparation/configuration is not a forwarding grant. BFF may wait up to30s for
its one original preparation/enrollment attempt (firmware HELLO retry is6s).
Every enrollment exchange and pending readiness retains its exclusive5s budget.
The readiness HTTP wait now anchors before query enqueue/owner processing,
limits submit to5s and never compares monotonic coordinates from different owners.
START still needs a fresh readiness token, physical binding and current lease.

Camera state keeps version2 as control-adapter metadata and adds contract_version3,
media_contract_revision, camera_contract_revision1.2 and cadence_revision.
An ACK is command_ack; actual_descriptor remains null without separate post-START
producer evidence. RTP freshness and browser decoded frames remain independent.

Camera-only lease exports add media_lease_expires_at, media_remaining_ms and an
immutable media_clock_id; see contracts/camera-media-v3-adapter/README.md and its
strict DTO schema/shared clock vectors. These fields never enter frozen common
media objects. Only authenticated owner-scoped camera1.2 HTTP may create the
anchor. Its current-UTC origin is captured once; active expiration and heartbeat
use issuer monotonic time plus Redis PTTL. Generic desktop touch is unchanged.
Active camera state captures the same clock ID, allowing BFF to reject a changed
anchor before any MEDIA renew. Owner/session/SN/scope/stream and active-key fences
remain mandatory; missing/corrupt/kernel-changed anchors never reinitialize an
active stream. Initial START is capped by the expiry used to prepare MEDIA even
when a heartbeat has since extended the server lease. Equality is expired.

## Release boundaries

Both native_auto_enabled and monotonic_runtime_enabled default false. Existing
writers_enabled and native_start_sns are not changed. Image packaging includes
the new03 and1.2 schema resources. The immutable0013 migration is additive;
application rollback retains its authority table/trigger and counters.

Owners must review exact revisions and clean source SHAs, then coordinate
MEDIA -> IoT -> MenuBuilder releases without enabling writers. A coordinator
separately assigns test SN, firmware installation and live acceptance; no such
action is performed by this candidate. PostgreSQL runtime tests need an isolated
camera_runtime_test URL and are skipped when unavailable; do not point them at
production. Offline actor/HTTP/mock-media tests do not prove hardware decoding.
