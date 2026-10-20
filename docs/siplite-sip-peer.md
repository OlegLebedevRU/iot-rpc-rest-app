# SIP peer diagnostics (siplite)

Method 174, CMD_SIP_PEER. Orchestration: siplite only, correlated /res,
no new events or STM32 operations. HTTP uses authenticated POST /local/rpc
with the same method_code/payload. status polling never starts a session.

Native ESP-RTC p2p_mode, UDP SIP and direct PCMA/8000 audio RTP between two
LAN endpoints; no REGISTER, PBX or PC audio relay. READY means the local
endpoint is initialized, not registered and not yet connected.

payload: {"dt":[{...}]} exactly one object. Actions:
- status: {"action":"status"}.
- prepare: action, session_id (32 lowercase hex), peer_ip (unicast LAN IPv4),
  local_port and peer_port (1024..65535), local_user and peer_user
  (1..15 ASCII letters/digits/_/-), lease_sec (30..60), duration_sec (10..3600).
  The UI uses unpredictable session-specific endpoint users. The peer identifier
  must match before explicit answer; this is a trusted-LAN diagnostic, not SIP
  digest authentication. No global auto-answer.
- dial / answer / renew / stop: action and matching session_id.

Both devices must be prepared with reciprocal addresses/ports/users and the
same session_id. Wait for both ready, dial once on chosen initiator, wait for
incoming on receiver and answer explicitly. connected requires audio-session
begin on both; UI also displays PCM and traffic counters when advertised.
Renew every 10 seconds. Lease and absolute duration start at prepare admission;
renew extends only the lease, never the absolute duration. UI failure/close
stops both sides, unreachable endpoints expire locally. No automatic retry of
mutations, no implicit reconnect/restart of a previous call.

All parameters remain RAM-only. cfg_sip/sip_enabled/URI and frontend scripts are
never rewritten. One RTC stack: stop ordinary SIP before creating diagnostics;
release diagnostics then restore ordinary SIP only if its persisted enable and
current policy allow it. Peer diagnostics, UDP diagnostics and Internet audio
are mutually exclusive under the existing audio owner. Camera video may coexist.
Ordinary outbound calls, maintenance, policy denial and endpoint/network loss
cancel diagnostics. No auto-resume after reboot or maintenance.

Responses: schema_version=1, method_code=174, hardware_id, boot_id, status,
session_id, state (idle/preparing/ready/calling/incoming/connected/stopping/error),
remaining_sec, duration_remaining_sec, reason, peer_ip, local_port, peer_port,
local_user, peer_user. Secrets and persistent SIP credentials are not returned.
200: status/idempotent stop/renew; 202: accepted asynchronous transition;
400: invalid schema/range; 409: ownership/session/state conflict; 403: policy;
503: service unavailable. Failed or ambiguous commands require fresh status,
not a blind replay. Active-session prepare returns 409.

ESP-RTC native address parsing limits each user to15 characters; the UI creates
12-character random users. Firmware constructs `peer_user@peer_ip:peer_port`
for `esp_rtc_call`, rather than passing the bare username.
