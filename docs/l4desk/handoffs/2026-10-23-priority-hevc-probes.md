# HEVC capability negotiation window

The real terminal773 could not finish fresh priority/background hardware
negotiation reliably inside the previous5s request. The frozen inventory_get
fixture already uses10s. The capability query and its MQTT TTL now use that
window; stream first-frame targets, leases, stream_start deadlines, cached
pre-query rejection, epoch and identity fences remain unchanged.

Native l4tools starts at Medium and avoids a secondary activation outside the
remaining query budget. MenuBuilder separately preserves the actual negative
reason instead of mislabelling probe_timeout as profile_unsupported.

98 video-v2 tests passed, including a fresh6.2s ACK and expired/pre-query refusal.
Ruff/Black changed files passed. Focused Pyright reports4 existing Redis
bytes-versus-str errors at lines62/71/200/231, before the changed negotiation
region; no introduced type errors. This is not a green whole-project Pyright
claim. No contract/schema or migration change. Deployment/real browser repeat
acceptance remain pending at this source checkpoint.
