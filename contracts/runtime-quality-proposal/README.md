# Runtime quality candidate 0.1

**Not activated.** This packet is a proposed extension to existing quality
set/report messages, not a replacement media descriptor or frozen camera schema.

- `schema.json`: structural JSON Schema generated from the typed candidate.
- `manifest.json`: exact candidate and unchanged common media schema pins.
- `verify.py`: offline verifier of structural/model agreement and semantics.
- `../../docs/runtime-quality-camera-candidate.md`: ownership, fields, time,
  compatibility, implementation boundary and rollout.
- `../../app-service/tests/core/camera/test_quality_contract.py`: executable
  boundary vectors, including high bitrate, arbitrary raster, fractional FPS,
  native Auto, down/recovery and a delayed command deadline.

Run from the repository root with its uv environment:

```powershell
uv run python contracts/runtime-quality-proposal/verify.py
uv run pytest app-service/tests/core/camera/test_quality_contract.py -q
```

These checks neither publish MQTT nor use PostgreSQL, hardware or a browser.
No admission/replay/physical authority is conferred by successful parsing.
