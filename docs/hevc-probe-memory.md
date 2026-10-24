# HEVC probe memory: IoT handoff

2026-10-24. Local implementation on b30f0a4807745e3ed3e2c3592b95ec62562e3d24.
No commit, publication, runtime patch or deploy performed.

Owner: IoT capability query/correlation; producer native l4desk, consumer MB BFF.
Contract: contracts/hevc-probe-memory-v1. Frozen G0 files are unchanged.
Optional measured_at_ms keeps the actual measurement time; checked_at_ms is the
current applicability check and must still satisfy the live correlated query.
Reject measured > checked, null, malformed values, old nonce/source/epoch/TTL.

Existing internal video-capabilities GET accepts optional profile_id low/default.
Forward to inventory_get, use it when testing snapshot cache hits and cooldown.
Do not let a cached Medium subset prevent a first HD check. Keep one live pending
query; do not replace it. No durable server store or START format changes.
Camera header branch and camera contracts remain unchanged.

Deploy IoT readers first, then updated l4desk, then MB profile sender/UI.
Old strict native agents reject profile_id. Existing requests omit it and keep
working during the staged update. New native ACKs include measured_at_ms.
No new MQTT client/type, topics or RPC method. Normal rollout uses accepted
repository source and immutable image through the existing app1 deployment flow;
no runtime-only patch and no .env/infrastructure edits.

Verification:160 relevant pytest passed (video_v2 and camera_negotiated),
Ruff isolated and Black check passed. Isolated prevents inheriting unrelated
outer l4tools config. Pyright has the same7 existing Redis/WS errors as baseline;
no new errors. Actual cached x86/x64 native fixture ACKs round-trip through the
production model. No real encoder/terminal acceptance performed.

Companion stacks: l4tools docs/hevc/mode-probe-memory-handoff.md and
MB docs/menu_arch-hevc-probe-memory.md. Patches and detailed logs retained in
l4tools .scratch/mode-memory/handoff and .scratch/mode-memory.
