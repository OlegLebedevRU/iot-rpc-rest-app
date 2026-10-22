# HEVC contract 2.0.0

Frozen wire definitions and offline conformance vectors for TASK-00. No product
implementation, live capability or E2E readiness is implied by this package.

`hevc.schema.json` uses JSON Schema draft 2020-12. `$defs` are independently
addressable entry points: `inventory_get`, `capabilities_ack`, `start`, `ready`,
`error`, `descriptor`, `media_start`, `media_renew`, `media_stop`, `media_response`,
`media_capabilities`, `media_health`, `rejection`, `stop`, `lease_renew`, `start_ack`, `nack`.
Unknown properties are forbidden recursively.
Fixtures wrap a **payload** with its target definition and expected validity;
only `payload` goes on the wire. Legacy schemas are snapshots of unchanged IoT
v1 models at `36814a1705216520bb841b6e52e57bdde07f9de7`.

The canonical narrative is `etranprocessing/docs/etran_arch-hevc-contracts.md`;
the rollout plan and media/siplite contract are alongside it. Source ownership,
stateful rules, authorization, projection, timing and rollback are normative
there. JSON Schema alone cannot prove them.

Run from any repository root:

```sh
uv run --no-project --with jsonschema==4.26.0 python contracts/hevc-v2/verify.py
```

In IoT, additionally exercise the actual legacy reader without importing the
application or opening a DB/broker connection:

```sh
uv run --no-project --with jsonschema==4.26.0 --with pydantic==2.12.3 python contracts/hevc-v2/verify.py --iot-source app-service/core/remote_input/schemas.py
```

`scenarios.json` is a PREPARE decision matrix. Its `start` field is a **candidate**,
not a command authorized for execution. An Auto result `h264` requires preparation
of a new concrete H.264 descriptor before route/START; the candidate HEVC descriptor
must never be executed as H.264. The oracle is test support, not a product resolver.
`lifecycle.json` specifies guarded lifecycle effects. Product implementations must
run these vectors against their real handlers in TASK-10/20/30.

`manifest.json` hashes every package file except itself, using LF UTF-8 bytes.
The aggregate SHA-256 is the hash of the JSON path-to-hash map, sorted keys and
compact separators. Each repository's CI pins that same digest. `--peer PATH`
also detects missing/extra/changed files in another checkout. Do not regenerate
a manifest merely to silence a mismatch: a contract change needs a shared revision
and updated copies/CI pins in all three repositories. The fixtures contain only
synthetic IDs, localhost destinations and no service token, PIN or credentials.

`native_legacy_reader.c` is an offline smoke for the unchanged native JSON decoder.
In an x86 or x64 MSVC developer prompt, from the l4tools repository root, create an
output directory outside this package and compile with `/MT /W4 /WX`:

```bat
cl /nologo /O2 /MT /W4 /WX /D_CRT_SECURE_NO_WARNINGS /I tools\l4desk\src /Fo<out_dir>\ contracts\hevc-v2\native_legacy_reader.c tools\l4desk\src\json_min.c /link /OUT:<out_dir>\native_legacy_reader.exe
<out_dir>\native_legacy_reader.exe contracts\hevc-v2\legacy\h264_start.wire.json contracts\hevc-v2\legacy\stop.wire.json
```

Repeat in both architecture prompts. This decodes fixtures only: no command handler,
input injection, agent, capture process, MQTT connection or service is started.
