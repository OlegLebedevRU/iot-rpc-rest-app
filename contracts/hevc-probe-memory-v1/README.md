# hevc-probe-memory/1.0

Desktop extension of frozen hevc-v2/2.0.0 and hevc-source-probe/1.0. Frozen files
and digest are unchanged. Old strict consumers reject new properties: update
readers before sending extended capabilities or requests.

capabilities.schema.json replaces only $defs.capabilities in runtime validators.
Optional integer measured_at_ms is 1..5000000000000. Omit it for old producers
and responses without successful evidence; explicit null is invalid.
Consumers additionally require measured_at_ms <= checked_at_ms.

- measured_at_ms: actual successful encoded measurement, retained on cache hits;
  for profiles from different probes, the earliest measurement used in this response.
- checked_at_ms: terminal-side applicability check after the correlated query's
  issued_at_ms. Old producers retain their original measurement semantics.
- valid_until_ms: snapshot expiry; existing maximum 60000ms remains.

encoded_sequence still requires real output for every advertised profile.
An old measurement can satisfy a new query only after validating the current
capture context. Correlation, SN/source, epoch, TTL, geometry and START checks
remain. Disk records never restore old agent IDs, revisions or permissions.

inventory_get.schema.json adds optional profile_id: low|default. Without it,
retain Medium-first/available-subset behavior. With it, the cache must contain
that profile to avoid probing. Missing HD can be measured without repeating
verified Medium. The existing IoT internal video-capabilities GET also accepts
optional profile_id. No new START fields, topics or MQTT clients.

IoT retains its short-lived snapshot cache and adds probe_profile_id alongside
probe_source_id for cooldown. Another profile's cached subset/cooldown cannot
prevent the first requested-profile check. Live pending requests are not replaced.

MB forwards profile_id only for Windows disp: sources. Desktop hevc_available
allows selecting an applicable verified profile; allocation conflicts remain
START errors. Unknown busy is shown as a deferred check. Camera contracts,
headers, START and firmware writers are unchanged.

Rollout: IoT/MB capability readers → updated l4desk → MB profile selector/UI.
Do not send profile_id to an old strict native reader. Old payloads remain valid:
the new properties are optional. New native positive replies include measured_at_ms.

Canonical identical copies: l4tools, IoT, etranprocessing. Runtime copies:
IoT core/remote_input/video_{inventory,capabilities}_memory.schema.json;
MB app/contracts/hevc_capabilities_memory.schema.json; native command closure
in video_wire_schema.h. See the repository-specific handoff for baselines and checks.
