# Bounded replay fences for existing media RPCs

This is an implementation reliability rule for existing RPC172 prepare, RPC173 start, RPC174 prepare and legacy camera RPC162/163/164. No new methods, events, fields or STM32 commands are introduced. Existing audio RPCs remain ESP32-local RES/CMT transactions; camera operations preserve their existing camera/gauge/RES behavior.

Before a previously unseen cloud request can prepare or start an audio session or execute a legacy camera mutation, the device durably records its nonzero task UUID and integral positive created_at timestamp. This storage commit precedes effects. Storage failure prevents effects even when the write outcome is ambiguous.

While the original RAM receipt is retained, existing response replay and payload-conflict checks apply. After reboot or receipt eviction, a recorded UUID must not execute again. It is rejected as replay_window_closed/outcome_unknown rather than claiming that its original operation completed. The caller reconciles current state through existing read APIs and uses a new task UUID for a new intent. External camera effects are not exactly-once without recipient support.

The fence retains sixteen recent UUIDs per owner and an eviction timestamp watermark. Unknown requests at or below that watermark are rejected, including conservative rejection of timestamp ties. Existing created_at is required; no new envelope field is added.

Session-scoped audio renewal/stream-start/stop continue to require the active session identity and lease. The preparation fence writes once per new session admission (172/174 prepare or 173 start), never once per renewal or media packet. Session state does not survive reboot. For cloud RPC172/174 renewals, the device also keeps one created_at high-water mark per method in RAM. After the RAM response receipt is gone, a renewal at or below that mark is rejected (including timestamp ties); only a newly created renewal can extend the lease. This adds no flash write. A reboot removes the volatile session itself. Existing retained RAM receipts still replay their original responses before this check. This rule does not claim durable RES storage for every audio method.

Local authenticated controls are outside cloud task replay protection. Their explicit operator operations and bounded resource ownership continue to apply.
