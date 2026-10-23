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
claim. No contract/schema or migration change. Builder suite733 passed,33 skipped.
Deployment is verified: source f73bfb7bba9657753f9504e5670b60d5c86b423e,
image sha256:1599c70f6f2faf7b38e43f4d3a56d15ad914cf1a33ccf3291eb21aef1e751bb6.
All13 image layers scanned without real secret findings; two cryptography
OpenSSH delimiters were reviewed as false positives. No active video leases at
rollout; HEVC flags retained and ten unrelated containers unchanged. Real browser
repeat acceptance remains a separate check against the installed native agent.

That check subsequently passed on the owner's773 with installed native1.13.48:
actual browser H26560s/296 frames and45s/204 frames after71s idle; H26430s/85
frames. No observed frame-growth stops. No new full-pilot or latency admission.
Final server snapshot: all13 environment hashes unchanged from pre-rollout;
ten unrelated container IDs/images retained. Initial MenuBuilder rollout lost
its existing operator override; restoring it with the same digest fixed
disabled_by_policy without extending the one-SN allowlist.
