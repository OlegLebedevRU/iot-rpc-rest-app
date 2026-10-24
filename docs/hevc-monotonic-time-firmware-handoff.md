# Firmware handoff: HEVC lease, TTL and START without device UTC

Status: implementation under verification, not deployed. The installed 1.13.52
and accepted IoT PR132 / MB PR107 contain probe memory, not this clock fix.
Publication and deployment evidence must be added before claiming acceptance.

## Ownership and actual scope

IoT owns pending nonce, lease, command production and server-side expiry.
MenuBuilder owns publisher START orchestration. l4desk owns Windows CTLv2
admission, local monotonic deadlines and persistent hardware proof.
Camera firmware and its CTLv1 producer remain a separate owner/contract.
Frozen HEVC2.0 and camera schemas are unchanged. The explicit extension is
contracts/hevc-monotonic-v1; there are no new START/STOP/RENEW wire fields.

## Server changes for Windows desktop

- Optional capability admission_clock has exactly one accepted value:
  issuer_monotonic_v1. Absent means legacy; null/false/unknown values are invalid.
- Before a new publisher START for a disp: source advertising this marker,
  MB obtains a fresh applicability ACK via existing IoT inventory refresh=true.
  This bypasses snapshot read cache/cooldown, not an already pending request.
  Saved matching hardware facts answer without an encoder probe.
- The ACK still requires the pending nonce, SN, source, server epoch and server
  timeout. A saved H.265 success grants neither lease nor START permission.
- checked_at_ms is query.issued_at_ms plus locally elapsed query/check duration,
  not device RTC. measured_at_ms is optional diagnostic information. Hardware
  proof does not expire just because a clock moved or the encoder is busy.

## Deadline rule implemented in l4desk

R is the local monotonic tick of the exact fresh applicability snapshot used
by START; I is that START's server issued_at_ms. R precedes START construction.
Bind R and I in RAM to boot/agent, capability, lease, stream and descriptor.
They cannot be supplied as trusted local fields in a received payload.

| Check | Local deadline |
| --- | --- |
| Initial START command | R + (START.expires_at_ms - I) |
| Initial lease | R + (START.lease_expires_at_ms - I) |
| Later STOP/RENEW command | R + (command.expires_at_ms - I) |
| Renewed lease | R + (renew.lease_expires_at_ms - I) |

Use differences from one issuer only. Command intervals must be positive and
at most 60000ms. Reject at now_tick >= deadline. This mapping may end early;
transport/queue delay never grants another full TTL at receipt. Do not compare
these server dates to device UTC and do not synchronize RTC as admission.

The active anchor never moves on capability reads or renewals. Duplicate START
does not reset it or start another encoder. An expired/stopped stream cannot
be revived by renew or a repeated START. Older/duplicate renewals do not extend
the deadline. A new boot discards admission state; only hardware proof survives.
Use a monotonic counter of sufficient width, checked addition and an explicit
wrap/reboot policy. Windows uses GetTickCount64, not a persisted uptime value.

## Camera CTLv1: unchanged fields, coordination required

Current camera START is StreamStartCommand v1: command_id, lease_id, sn,
mode=usb-camera, source_id, profile=default, stream_instance_id, issued_at_ms
(server publication time), expires_at_ms (lease expiry). START does not carry
ttl_sec. STOP uses publication time + 5000ms. CameraRenewCommand adds ttl_sec=60
and its expiry is the lease expiry. No ttl_ms, lease_remaining_ms, local anchor
or desktop applicability handshake has been added to this camera path.

Therefore do not advertise issuer_monotonic_v1 on cameras or copy the Windows
formula without a correlated readiness point preceding server budget creation.
Firmware/server owners must agree that handshake and its revision together.
Starting a full ttl_sec on delayed packet receipt is not equivalent. The camera
test START handoff and firmware-writer gates remain independently applicable;
this change does not enable firmware writers or expand camera allowlists.

## Required coordinated acceptance

Cover RTC offsets of days and jumps while streaming; delayed START at and beyond
the deadline; wrong/expired nonce and old boot; duplicate START without a second
encoder; reordered/duplicate renewals; renew at/after lease expiry; STOP then
replayed START; restart with saved hardware proof but no saved admission; timer
wrap/overflow. Server nonce expiry and device monotonic expiry are separate checks.

Rollout: marker-aware IoT reader and MB START first, new native agent second.
Legacy Windows agents retain their old time assumptions until upgraded. No
camera deployment, stable/fleet admission or firmware compatibility is implied.
Machine-readable cases: contracts/hevc-monotonic-v1/vectors.json.
