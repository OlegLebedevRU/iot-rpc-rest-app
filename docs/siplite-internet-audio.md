# siplite Internet audio — RPC173

Device-specific ESP32 transaction, correlated RES only, no new EVT and no
STM32 command. Existing SIP lifecycle events remain unchanged. User accepts
that incoming SIP calls cannot be received while the SIP service is suspended.
HTTP POST /local/rpc uses the same dispatcher and schema. Settings are volatile.

## Request

Exactly one payload.dt object. Unknown fields reject the entire request.

Start:
```json
{"dt":[{"action":"start","session_id":"00112233445566778899aabbccddeeff","url":"https://example.org/announcement.mp3","format":"mp3","duration_sec":300,"loop":false}]}
```

`session_id`: 32 lowercase hexadecimal characters, client generated.
`url`: HTTP/HTTPS, maximum511 UTF-8 bytes; direct media URL, not a webpage.
`format`: mp3, aac, wav or hls_aac. Required: no unreliable extension guessing.
`duration_sec`: integer1..86400, mandatory. `loop`: boolean, default false;
allowed for direct files only, not hls_aac. HLS support is limited to compatible
unencrypted audio AAC playlists/segments; unsupported containers/DRM reject or
fail explicitly. MP3/AAC Icecast streams must use HTTP-compatible headers and
must not insert unhandled ICY metadata. HTTPS verifies the server certificate.

Stop: `{"dt":[{"action":"stop","session_id":"00112233445566778899aabbccddeeff"}]}`.
Status: `{"dt":[{"action":"status"}]}`. Stop is scoped to the session: stale
session IDs cannot stop a newer stream. Duplicate active start with identical
parameters returns current state and never extends deadlines; same session
with different parameters conflicts. Completed session IDs cannot restart by
replay within the boot's bounded result history (16 entries); old session IDs
beyond this retention window are not a durable idempotency key. Reboot clears
history. Clients generate fresh IDs and do not replay an ambiguous start.

## Response/lifecycle

Start RES200 means accepted (`preparing`), not proof that sound has played.
Status fields: `v=1`, `hardware_id`, `session_id` (or null), `state`, `reason`,
`remaining_sec`, `duration_sec`, `loop`, `format`, `sip_suspended`,
`source_rate_hz`, `output_rate_hz`, `pcm_bytes`. URL is not echoed (signed query
strings may be credentials). States: idle/preparing/buffering/playing/stopping/
restoring/stopped/error. State is polled; no completion EVT is added.

The playback deadline begins on first successful PCM output. It uses monotonic
RAM time and is not extended by repeats/rebuffering. Preparation has a separate
bounded deadline (180 seconds); network stalls after playback terminate within
30 seconds and still consume the playback duration. EOF without loop stops
early. Stop/timeout/EOF/policy/network/decode errors close and join pipeline
resources before audio ownership is released. Reboot never resumes playback.
Terminal reason distinguishes eof, duration_expired, operator_stop, sip_call,
maintenance, policy_denied, start_timeout, stream_error and restore_failed.

400 malformed schema;403 policy/SIP disabled where applicable;409 audio or
maintenance busy, conflicting session/replayed terminal start;422 unsupported
parameters;503 worker/resources unavailable;500 internal failure. Stop RES200
may report stopping; status confirms teardown. No blind retries after unknown
outcomes. RPC task TTL (minutes) is distinct from playback duration (seconds).

## Admission and SIP

One short admission lock and token/epoch covers SIP transitions/calls, Internet
playback, active audio diagnostics (P2P/capture/test playback), and tone output.
Passive status/levels do not claim the hardware. No network, Flash, SIP teardown,
registration wait or task join under the admission lock.

An active SIP call or active diagnostics rejects Internet start. If SIP is only
registered/idle, Internet playback suspends and fully deinitializes its service,
not merely microphone/DAC. A fresh concurrent call wins admission or returns a
bounded busy result; two owners never initialize the audio hardware together.

Outgoing call requests copy the target into a bounded volatile pending slot.
When SIP mode is enabled and an Internet stream/diagnostics owns audio, stop and
join that owner, restore the phone clock profile, start SIP through its lifecycle
manager, await REGISTERED (bounded60 seconds after teardown), then dial exactly
once. Hangup cancels the pending request. SIP disabled/policy denial/maintenance
reject the request; repeated requests do not overwrite the pending destination.
No dialing from the SIP event callback and no blocking of peripheral input code.

On normal playback end restore SIP only if currently enabled, policy allows it
and maintenance is inactive. A disabled mode is never automatically enabled.
No automatic resumption of the Internet stream after a call. Diagnostics follows
the same admission rules and retains its existing RPC170/171/172 contract.
Maintenance closes admission, cancels Internet/diagnostics, waits for confirmed
teardown, then performs its existing exclusive update operation.

## Custom content

Host MP3/AAC/WAV on an ordinary HTTP/HTTPS server and pass its direct URL. The
ESP32 plays progressively; no firmware upload or NVS/Flash media cache is used.
LAN HTTP servers are allowed for operator-hosted content. A PC-hosted URL works
only while that server is reachable. Individual HTTP players are not sample-
synchronized multiroom broadcast. HLS is for compatible segmented live sources.
