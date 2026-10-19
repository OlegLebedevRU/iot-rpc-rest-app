# Siplite live audio control: RPC170/171/172

Status: proposed v1 contract for siplite. ESP32 executes these methods directly;
no STM32 command/register changes. Every accepted RPC completes with correlated
RES on the existing dev/<SN>/res topic, stable result_uid and transport
status_code. No new EVT, gauge, webhook type, property tag or MQTT topic.
Clients poll both device states; task completion does not prove audible sound.

## Methods and local HTTP

170 CMD_AUDIO_GET_STATE: payload={"dt":[{}]}.
171 CMD_AUDIO_SET_CONFIG: exactly one dt item with expected_revision (opaque
string from170), dry_run (boolean, default false) and nonempty patch object.
172 CMD_AUDIO_SESSION: exactly one dt item with action prepare/start/renew/stop.

Local PIN-authenticated GET /local/audio and POST /local/rpc use the same owner
and validation; the latter accepts {"method_code":170|171|172,"payload":...}.
State includes hardware_id; clients verify it against their authenticated slot.

## State and settings

Return schema_version=1, hardware_id, boot_id, revision, config, observed,
capabilities and session. Observed values and metrics may be null when not
measured. capabilities describes readable/writable fields, exact allowed values,
units, supported sample rates/codecs, source points and restart requirements.
Do not advertise unsupported hardware parameters as writable.

Config controls include speaker_volume (integer0..100), speaker_mute (boolean),
mic_gain_db and reference_gain_db (exact PGA values0,3,6,9,12,15,18,21,24,27,
30,33,34.5,36,37.5), adc_volume_db (0.5dB steps where supported), adc_scale_db,
adc_hpf and supported AEC enable/filter parameters. Independent mic/reference
settings preserve register input selection and channel mapping. Raw register
access is excluded. Clock/rate/word width and routing changes require an explicit
stopped session and advertised validated combinations. Runtime settings are
volatile unless a separately advertised persistence operation succeeds.

Prevalidate the whole patch, reject unknown or duplicate fields, NaN/nonintegral
values where integer is required, unsupported combinations and stale revisions.
Never clamp silently. Serialize mutations, verify hardware readback, and return
applied_fields only after verification. A failed read is not a zero value.
Possible outcomes: applied, unchanged, validation_failed, busy, verify_failed,
partial_apply, outcome_unknown. Return effective state after the operation.
Status200=verified/unchanged/dry_run;202=accepted pending lifecycle;
400=invalid schema;422=unsupported value;409=stale revision/owner conflict;
503=temporarily unavailable;500=internal failure. Physical sound/power/AEC
quality must never be inferred from register readback alone.

## Session control

Prepare requires session_id (32 lowercase random hex characters), peer_ip
(numeric unicast LAN IPv4), local_port and peer_port (1024..65535), direction
(tx/rx/duplex), source (raw_mic/post_aec), sample_rate_hz, codec, frame_ms and
lease_sec (5..60). Both peers must use the same supported media format and
session_id. No implicit SIP call, automatic peer discovery or arbitrary hostname
resolution. A session token is provided in the sensitive field token (64 hex
characters) to authenticate packets; never echo it in state/results/logs. Existing
RPC redaction already masks token in histories; it does not alter wire delivery.
Only authenticated control requests may install this credential.

Start, renew and stop carry only action and session_id (renew may include the
bounded lease_sec). Different session IDs conflict with an existing owner.
Duplicate start for the same running session is unchanged, not a restart.
A repeated stop of the last stopped session is unchanged. Renew is refused
once stopping or expired. Lifecycle states: idle, preparing, prepared, starting,
running, stopping, error. Pending RES means accepted only; poll to establish
prepared/running/stopped. Error does not mean resources are already released.

Lease expiry uses monotonic time and stops capture/playback. The controller
prepares receiver then sender; after both report prepared it starts both and
renews only while both hardware identities/states match. Any failed operation
or lost peer stops the pair and stops renewals. No mutation replay on reconnect.
OTA/network shutdown cancels/joins debugging before reclaiming audio resources.
SIP, local tones and debug have exclusive audio ownership. Stop restores the
normal profile and SIP according to persisted settings/policy, not unconditional
registration. State includes lease remaining, peer/session/direction, counters
and last_error, without the token. Control and media policy boundaries must be
explicit; unsupported/admission-denied requests must not quietly enable media.

## UDP framing v1

Header is28 bytes: ASCII L4AU[4], version u8=1, codec u8 (0=PCM16LE,
1=G711A), samples u16 big-endian, session_id[16] decoded from hex, sequence
u32 big-endian. Payload length is samples*2 for PCM or samples for G711A.
Append the first16 bytes of HMAC-SHA256(header||payload), keyed by decoded
32-byte token. Frames have fixed samples=rate*frame_ms/1000 for the prepared
format. Sender sequence increments modulo2^32; receiver validates peer endpoint,
exact length, session, format and MAC before replay/jitter processing. Packet
credential authenticates, does not encrypt audio: this v1 is for a trusted LAN.

Use a bounded jitter buffer and paced playout. Track received/auth_failed/lost/
reordered/late/rendered frames, conceal gaps with silence and reject stale or
replayed frames. Sequence discontinuity is not a new session. Never allocate
based on untrusted packet lengths. State distinguishes packets received from
frames actually rendered. PCM peak/RMS/clipping reports identify the tap point
(raw microphone/reference, processed microphone, playback) and measurement age.

## Acceptance and compatibility

A firmware advertises implemented capabilities; this document does not claim
that deployed devices already support these methods. Verify one-way both ways,
duplex with AEC, independent gains, readback failures, invalid requests, stale
revisions, packet replay/jitter, lease expiry, peer loss, close and OTA teardown.
Client/firmware changes follow this upstream PR. No peripheral firmware change.
