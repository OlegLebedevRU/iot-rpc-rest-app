# Siplite: unsupported legacy operations

This capability correction applies to siplite, not to other device families.
It does not remove method codes from the common registry.

The audited siplite implementation contains no executable operation for:
16 LOAD_CARDS_FROM_CLOUD, 17 LOAD_CONFIG_FROM_CLOUD, 18 SEND_485,
26 ERASE_CARDS, 34 ERASE_LOG, 42 ASCII_TO_UART and 47 DELETE_CARDS.
Commented-out transport/database code must not result in a successful RES.
In particular, the l4-hmi UI-Catalog implementation of17 is unaffected.

A valid request for one of these unsupported operations completes with the
existing correlated RES envelope and transport status_code=501.
The body uses the normal status=ERROR, method-name, message and error-name representation and
explicitly states that the operation is not implemented by this firmware.
No UART, I2C, database, log erasure or other external side effect is performed.
No completion EVT is emitted for an operation which was never executed.
Invalid envelopes may still fail earlier under the normal schema rules.

The device uses the task UUID as the stable result_uid for this deterministic
unsupported result. Repeated delivery of the same valid request may regenerate
the same result without persistent receipts: there is no operation to repeat.
This does not promise autonomous RES retry if both the result and subsequent
task redelivery are absent. An upgraded firmware which actually implements a
method must establish its execution and result-replay contract first.

This is an ESP32-local capability/error correction. It adds no method/event,
payload tag, topic, STM32 register or bus command and does not implement these
legacy features. Clients must treat501 as unsupported, never as successful
execution, and must not use it as a reason to retry a destructive operation
blindly with a new task identity.

Acceptance: all seven methods return non-success without side effects;
unsupported RS485 does not allocate/decode throwaway buffers or delay;
repeated results preserve identity/content; implemented neighboring methods
retain their existing paths. Hardware checks may use these methods only after
the corrected firmware identity is confirmed.
