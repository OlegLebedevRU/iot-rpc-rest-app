# Bounded replay fences for existing media RPCs

This is an implementation reliability rule for existing RPC172 prepare and legacy camera RPC162/163/164. No new methods, events, fields or STM32 commands are introduced. Existing audio RPCs remain ESP32-local RES/CMT transactions; camera operations preserve their existing camera/gauge/RES behavior.

Before a previously unseen cloud request can prepare an audio session or execute a legacy camera mutation, the device durably records its nonzero task UUID and integral positive created_at timestamp. This storage commit precedes effects. Storage failure prevents effects even when the write outcome is ambiguous.

While the original RAM receipt is retained, existing response replay and payload-conflict checks apply. After reboot or receipt eviction, a recorded UUID must not execute again. It is rejected as replay_window_closed/outcome_unknown rather than claiming that its original operation completed. The caller reconciles current state through existing read APIs and uses a new task UUID for a new intent. External camera effects are not exactly-once without recipient support.

The fence retains sixteen recent UUIDs per owner and an eviction timestamp watermark. Unknown requests at or below that watermark are rejected, including conservative rejection of timestamp ties. Existing created_at is required; no new envelope field is added.

Audio renewal/start/stop continue to require the active session identity and lease. The preparation fence writes once per new prepare, never once per renewal or media packet. Session state does not survive reboot. This rule does not claim durable RES storage for every audio method or guarantee against all delayed renewals within the same still-live session.

Local authenticated controls are outside cloud task replay protection. Their explicit operator operations and bounded resource ownership continue to apply.
